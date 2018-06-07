
import platform
import re
import sys
from .DataGridder import DataGridder
from . import ContourUtils
from . import ContourMethod

qgis_qhull_fails=platform.platform().startswith('Linux')

from qgis.core import (
    QgsExpression,
    QgsExpressionContext,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsGeometry,
    QgsPointXY,
    QgsFields,
    QgsWkbTypes
    )
from PyQt5.QtCore import (
    QObject,
    QVariant
    )

_mplAvailable=False
try:
    import numpy as np
    from matplotlib.pyplot import contour, contourf, tricontour, tricontourf
    from matplotlib.mlab import griddata
    from matplotlib.tri import Triangulation, TriAnalyzer
    _mplAvailable=True
except ImportError:
    _mplAvailable=False
    pass

class ContourError( RuntimeError ):
    pass

class ContourGenerationError( ContourError ):
    pass

class _DummyFeedback:

    def isCanceled( self ):
        pass

    def setProgress( self, percent ):
        pass

    def pushInfo( self, info ):
        pass

    def reportError( self, message, fatal=False ):
        raise ContourError( message )

class ContourGenerator( QObject ):

    MaxContours=100
    translateExtend=lambda self, x: {'none':'neither','below':'min','above':'max'}.get(x.lower(),x.lower())


    def __init__( self, source=None, zField=None, feedback=None ):
        '''
        Initiallize the contour generator with source and field expression.
        The initiallization will attempt to load the data.

        If feedback is supplied it should support:
            fieldback.isCanceled()
            fieldback.setProgress(percent_progress)
            ...
        '''
        QObject.__init__(self)
        if not _mplAvailable:
            raise ContourError(self.tr("python matplotlib not available"))
        self._x = None
        self._y = None
        self._z = None
        self._origin = [0,0] # NOTE: calculate in data()
        self._source=None
        self._sourceFids=None
        self._zField = None
        self._zFieldName = None
        self._discardTolerance=0
        self._dataLoaded = False
        self._gridTested = False
        self._gridShape = None
        self._useGrid = True
        self._contourMethod = None
        self._contourMethodParams = None
        self._levels = None
        self._filledContours = False
        self._extendFilled = 'both'
        self._labelNdp = -1
        self._labelTrimZeros = False
        self._labelUnits = ''
        self._feedback = feedback or _DummyFeedback()
        self.setDataSource( source, zField )

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def _dataDef( self ):
        return (
            None if self._source is None else 'source', # self._source.id(),
            self._zField,
            self._discardTolerance
            )   

    # Functions to support null feedback
    def isCanceled( self ):
        return None

    def setProgress( self ):
        return None

    def setDataSource( self, source, zField=None, sourceFids=None ):
        if self._source != source or self._sourceFids != sourceFids:
            self.setReloadData()
        self._source=source
        self._sourceFids=sourceFids
        if zField is not None:
            self.setZField(zField)

    def setDiscardTolerance( self, discardTolerance ):
        if self._discardTolerance != discardTolerance:
            self._discardTolerance=discardTolerance
            self.setReloadData()

    def setZField( self, zField ):
        if self._zField != zField:
            self._zField=zField
            self._zFieldName=zField
            self.setReloadData()

    def setUseGrid( self, usegrid ):
        self._useGrid=usegrid

    def setContourMethod( self, levels ):
        self.setContourMethod('manual',{'levels':levels})

    def setContourMethod( self, method, params ):
        self._contourMethod=method
        self._contourMethodParams=params
        self._levels=None

    def setContourType( self, contourType ):
        contourType=contourType.lower()
        if contourType=='line':
            self._filledContours=False
        elif contourType=='filled':
            self._filledContours=True
        else:
            raise ContourError(self.tr("Invalid contour type {0}").format(contourType))

    def setExtendFilled( self, extend ):
        self._extendFilled=self.translateExtend(extend)

    def setLabelFormat( self, ndp, trim=False, units='' ):
        self._labelNdp = ndp
        self._labelTrimZeros = trim
        self._labelUnits = units

    def setReloadData( self ):
        self._dataLoaded=False
        self._gridTested=False
        self._levels=None

    def data( self ):
        if self._dataLoaded:
            return self._x, self._y, self._z
        self._dataLoaded=True
        self._x = None
        self._y = None
        self._z = None

        source=self._source
        zField=self._zField
        if source is None or zField is None or zField == '':
            return self._x, self._y, self._z

        discardTolerance=self._discardTolerance
        feedback=self._feedback

        total = source.featureCount()
        percent = 100.0 / total if total > 0 else 0

        count = 0
        x = list()
        y = list()
        z = list()
        try:
            if source.fields().lookupField(zField) >= 0:
                self._zFieldName=zField
                # Have had issues with losing field quoting 
                # and misinterpreting field names
                zField='"'+zField.replace('"','""')+'"'
            else:
                if re.match(r'^"([^"]|"")+"$',zField):
                    self._zFieldName=zField[1:-1].replace('""','"')
                else:
                    self._zFieldName="Expression"
            expression=QgsExpression(zField)
            if expression.hasParserError():
                raise ContourError(self.tr("Cannot parse")+" "+zField)
            fields=source.fields()
            context=QgsExpressionContext()
            context.setFields(fields)
            if not expression.prepare(context):
                raise ContourError(self.tr("Cannot evaluate value")+ " "+zField)
            request = QgsFeatureRequest()
            request.setSubsetOfAttributes( expression.referencedColumns(),fields)
            if self._sourceFids is not None:
                request.setFilterFids(self._sourceFids)
            for current,feat in enumerate(source.getFeatures( request )):
                try:
                    if feedback.isCanceled():
                        raise ContourError('Cancelled by user')
                    feedback.setProgress(int(current * percent))
                    context.setFeature(feat)
                    zval=expression.evaluate(context)
                    try:
                        zval=float(zval)
                    except ValueError:
                        raise ContourError(self.tr("Z value {0} is not number")
                                                   .format(zval))
                    if zval is not None:
                        geom = feat.geometry().asPoint()
                        x.append(geom.x())
                        y.append(geom.y())
                        z.append(zval)
                except Exception as ex:
                    raise
                    pass
                count = count + 1

            npt=len(x)
            if npt > 0:
                x=np.array(x)
                y=np.array(y)
                z=np.array(z)
                feedback.pushInfo("Discard tolerance {0}".format(discardTolerance))
                if discardTolerance > 0:
                    index=ContourUtils.discardDuplicatePoints(
                        x,y,discardTolerance,self.crs().isGeographic())
                    npt1=len(index)
                    if npt1 < npt:
                        x=x[index]
                        y=y[index]
                        z=z[index]
                        feedback.pushInfo("{0} near duplicate points discarded {0}"
                                          .format(npt-npt1))
        except ContourError as ce:
            feedback.reportError(ce.message)
            feedback.setProgress(0)
            return self._x,self._y,self._z
        finally:
            feedback.setProgress(0)

        self._x=x
        self._y=y
        self._z=z
        self._gridShape=None
        self._gridTested=False
        self._dataLoaded=True
        # NOTE: isgridded should be handled elsewhere probably`
        self.isGridded()
        return self._x, self._y, self._z

    def isGridded(self):
        """
        Check if points data are on a regular grid
        """
        if not self._gridTested:
            x,y,z=self.data()
            self._gridShape,self.gridOrder=DataGridder(x,y).calcGrid()
            self._gridTested=True
        return self._gridShape is not None

    def gridShape(self):
        return self._gridShape

    def levels( self ):
        if self._levels is None:
            x,y,z = self.data()
            method=self._contourMethod
            params=self._contourMethodParams
            if method is None:
                raise ContourError(self.tr("Contouring method not defined"))
            self._levels=ContourMethod.calculateLevels(z,method,**params)
        return self._levels

    def crs( self ):
        return self._source.sourceCrs()

    def wkbtype( self ):
        return QgsWkbTypes.MultiPolygon if self._filledContours else QgsWkbTypes.MultiLineString

    def fields( self ):
        zFieldName=self._zFieldName
        if self._filledContours:
            fielddef= [('index',int),
                       (zFieldName+"_min",float),
                       (zFieldName+"_max",float),
                       ('label',str)
                      ]
        else:
            fielddef= [('index',int),
                      (zFieldName,float),
                      ('label',str)
                      ]
        fields = QgsFields()
        for name, ftype in fielddef:
            fields.append(
                QgsField(name,QVariant.Int,'Int') if ftype == int else
                QgsField(name,QVariant.Double,'Double') if ftype == float else
                QgsField(name,QVariant.String,'String')
                )
        return fields

    def geometryFromMultiLineString(self,lines):
        glines=[]
        for l in lines:
            points=[QgsPointXY(x,y) for x,y in l]
            glines.append(points)
        geom=QgsGeometry.fromMultiPolylineXY(glines)
        geom.makeValid()
        return geom

    def geometryFromMultiPolygon(self,polygons):
        gpolys=[]
        for p in polygons:
            gpoly=[]
            interior,exterior=p
            ipoly=[QgsPointXY(x,y) for x,y in interior]
            gpoly.append(ipoly)
            for e in exterior:
                epoly=[QgsPointXY(x,y) for x,y in e]
                gpoly.append(epoly)
            gpolys.append(gpoly)
        geom=QgsGeometry.fromMultiPolygonXY(gpolys)
        geom.makeValid()
        return geom

    def contourFeatures(self):
        if self._filledContours:
            return self.filledContourFeatures()
        else:
            return self.lineContourFeatures()

    def _buildtrig_workaround( self, x, y ):
        '''
        Workaround implemented as qhull fails when called from
        within QGIS python in ubuntu 17.10, QGIS 3.1 :-( 
        ''' 
        import os
        import sys
        import subprocess
        import tempfile
        tfh,tfname=tempfile.mkstemp('.npy','tmp_contour_generator')
        tfh2,tfname2=tempfile.mkstemp('.npy','tmp_contour_generator')
        os.close(tfh)
        os.close(tfh2)
        trig=None
        try:
            np.save(tfname,np.vstack((x,y)))
            pydir=os.path.dirname(os.path.abspath(os.path.realpath(__file__)))
            pyscript=os.path.join(pydir,'buildtrig_qhull_workaround.py')
            python=sys.executable
            result=subprocess.call([python,pyscript,tfname,tfname2])
            triangles=np.load(tfname2)
            trig=Triangulation(x,y,triangles)
        finally:
            os.remove(tfname)
            os.remove(tfname2)
        return trig

    def buildTriangulation( self, x, y ):
        trig=None
        if qgis_qhull_fails:
            trig=self._buildtrig_workaround(x,y)
        else:
            trig=Triangulation(x,y)
        analyzer=TriAnalyzer(trig)
        mask=analyzer.get_flat_tri_mask()
        trig.set_mask(mask)
        return trig

    def computeContours(self):
        x,y,z=self.data()
        levels = self.levels()
        extend=self._extendFilled
        usegrid=self.isGridded() and self._useGrid
        if usegrid:
            shape=self._gridShape
            gx = x.reshape(shape)
            gy = y.reshape(shape)
            gz = z.reshape(shape)
            self._feedback.pushInfo("Contouring {0} by {1} grid"
                .format(shape[0],shape[1]))
            try:
                cs = contour(gx, gy, gz, levels, extend=extend)
            except:
                raise
                raise ContourGenerationError()

        else:
            try:
                self._feedback.pushInfo("Triangulating {0} points"
                    .format(len(x)))
                trig=self.buildTriangulation(x,y)
                self._feedback.pushInfo("Contouring {0} triangles"
                    .format(trig.triangles.shape[0]))
                cs = tricontour(trig, z, levels, extend=extend)
            except:
                raise
                raise ContourGenerationError()
        lines = list()
        levels = [float(l) for l in cs.levels]
        for i, line in enumerate(cs.collections):
            linestrings = []
            for path in line.get_paths():
                if len(path.vertices) > 1:
                    linestrings.append(path.vertices)
            lines.append([ i, levels[i], linestrings])
        return lines

    def computeFilledContours(self):
        levels = self.levels()
        x, y, z = self.data()
        extend=self._extendFilled
        usegrid=self.isGridded() and self._useGrid
        if usegrid:
            shape=self._gridShape
            gx = x.reshape(shape)
            gy = y.reshape(shape)
            gz = z.reshape(shape)
            self._feedback.pushInfo("Contouring {0} by {1} grid"
                .format(shape[0],shape[1]))
            try:
                cs = contourf(gx, gy, gz, levels, extend=extend)
            except:
                raise ContourGenerationError()
        else:
            try:
                self._feedback.pushInfo("Triangulating {0} points"
                    .format(len(x)))
                trig=self.buildTriangulation(x,y)
                self._feedback.pushInfo("Contouring {0} triangles"
                    .format(trig.triangles.shape[0]))
                cs = tricontourf(trig, z, levels, extend=extend)
            except:
                raise ContourGenerationError()

        # NOTE: Need to handle extend
        levels = [float(l) for l in cs.levels]
        if extend:
            levels = np.append([-np.inf,], levels)
            levels = np.append(levels, [np.inf,])

        polygons=[]
        for i, polygon in enumerate(cs.collections):
            mpoly = []
            for path in polygon.get_paths():
                path.should_simplify = False
                poly = path.to_polygons()
                exterior = []
                holes = []
                if len(poly)>0:
                    exterior = poly[0] #and interiors (holes) are in poly[1:]
                    #Crazy correction of one vertice polygon, mpl doesn't care about it
                    if len(exterior) < 2:
                        continue
                    p0 = exterior[0]
                    if len(poly)>1: #There's some holes
                        for h in poly[1:]:
                            if len(h)>2:
                                holes.append(h)

                mpoly.append([exterior, holes])
            if len(mpoly) > 0:
                polygons.append([i, levels[i], levels[i+1], mpoly])

        return polygons

    def calcLabelNdp( self ):
        # NOTE: Real intention of ndp < 0 is to automatically calculate a
        # precision appropriate to the contour levels/increment.  Note this
        # should be cached otherwise will be calculated for every label...
        return self._labelNdp

    def formatLevel( self, level ):
        ndp=self.calcLabelNdp()
        if ndp < 0:
            return str(level)
        elif self._labelTrimZeros:
            level=np.round(level,ndp)
            return str(level)
        else:
            return "{1:.{0}f}".format(ndp,level)

    def lineContourFeatures(self):
        lines = self.computeContours()
        fields=self.fields()
        dx,dy=self._origin
        zfield=self._zFieldName
        for i, level, line in lines:
            level=float(level)
            levels=self.formatLevel(level) + self._labelUnits
            try:
                feat = QgsFeature(fields)
                geom=self.geometryFromMultiLineString(line)
                geom.translate(dx,dy)
                feat.setGeometry(geom)
                feat['index']=i
                feat[zfield]=level
                feat['label']=levels
                yield feat
            except Exception as ex:
                message=sys.exc_info()[1]
                self._feedback.reportError(message)

    def _rangeLabel(self,min,max,units):
        op=' - '
        lmin=''
        lmax=''
        if np.isfinite(min):
            lmin=self.formatLevel(min)
        else:
            op='< '
        if np.isfinite(max):
            lmax=self.formatLevel(max)
        else:
            op='> '
            lmax=lmin
            lmin=''
        return lmin+op+lmax+units


    def filledContourFeatures(self ):
        polygons = self.computeFilledContours()
        fields = self.fields()
        symbols=[]
        ninvalid=0
        dx,dy=self._origin
        zminfield=self._zFieldName+'_min'
        zmaxfield=self._zFieldName+'_max'
        for i, level_min, level_max, polygon in polygons:
            level_min=float(level_min)
            level_max=float(level_max)
            label = self._rangeLabel(level_min,level_max,self._labelUnits)
            try:
                feat = QgsFeature(fields)
                try:
                    geom=self.geometryFromMultiPolygon(polygon)
                    geom.translate(dx,dy)
                    feat.setGeometry(geom)
                except Exception as ex:
                    ninvalid += 1
                    print("Exception:",ex)
                    continue
                feat['index']=i
                feat[zminfield]=level_min
                feat[zmaxfield]=level_max
                feat['label']=label
                yield feat
            except Exception as ex:
                self._feedback.reportError(ex.message)
