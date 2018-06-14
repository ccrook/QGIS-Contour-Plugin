
import platform
import re
import sys
import traceback
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
    QVariant,
    QCoreApplication
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

def tr(string):
    return QCoreApplication.translate('Processing', string)

class ContourError( RuntimeError ):

    def message(self):
        return self.args[0] if len(self.args)  > 1 else "Exception"

class ContourGenerationError( ContourError ):

    @staticmethod
    def fromException( excinfo ):
        message=traceback.format_exception_only(excinfo[0],excinfo[1])
        return ContourGenerationError(message)

class ContourExtendOption:

    both='both'
    below='min'
    above='max'
    neither='neither'

    _options=[both,below,above,neither]
    _above=[both,above]
    _below=[both,below]

    _description={
        both: tr('Fill below minimum and above maximum contour'),
        below: tr('Fill below minimum contour'),
        above: tr('Fill above maximum contour'),
        neither: tr('Don\'t fill below or above maximum contour')
        }

    def options():
        return ContourExtendOption._options

    def valid( option ):
        return option in ContourExtendOption._options

    def description( option ):
        return ContourExtendOption._description.get(option,tr('Invalid contour option {0}').format(option))

    def extendBelow( option ):
        return option in ContourExtendOption._below

    def extendAbove( option ):
        return option in ContourExtendOption._above

class ContourType:
    line='line'
    filled='filled'
    layer='layer'

    _types=[line, filled, layer]

    _description={
        line: tr('Contour lines'),
        filled: tr('Filled contour polygons'),
        layer: tr('Layer contour polygons')
        }

    _wkbtype={
        line: QgsWkbTypes.MultiLineString,
        filled: QgsWkbTypes.MultiPolygon,
        layer: QgsWkbTypes.MultiPolygon,
        }

    def types():
        return ContourType._types

    def valid( type ):
        return type in ContourType._types

    def description( type ):
        return ContourType._description.get(type,tr('Invalid contour type {0}').format(type))

    def wkbtype( type ):
        return ContourType._wkbtype.get(type)

class _DummyFeedback:

    def isCanceled( self ):
        return False

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
            raise ContourError(tr("python matplotlib not available"))
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
        self._gridOrder = None
        self._useGrid = True
        self._contourMethod = None
        self._contourMethodParams = None
        self._levels = None
        self._contourType = ContourType.line
        self._extendFilled = ContourExtendOption.both
        self._labelNdp = -1
        self._defaultLabelNdp = None
        self._labelTrimZeros = False
        self._labelUnits = ''
        self._feedback = feedback or _DummyFeedback()
        self.setDataSource( source, zField )

    def _dataDef( self ):
        return (
            None if self._source is None else 'source', # self._source.id(),
            self._zField,
            self._discardTolerance
            )   

    # Functions to support null feedback
    def isCanceled( self ):
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

    def setContourLevels( self, levels ):
        self.setContourMethod('manual',{'levels':levels})

    def setContourMethod( self, method, params ):
        self._contourMethod=method
        self._contourMethodParams=params
        self._levels=None

    def setContourType( self, contourType ):
        contourType=contourType.lower()
        if not ContourType.valid(contourType):
            raise ContourError(tr("Invalid contour type {0}").format(contourType))
        self._contourType=contourType

    def setContourExtendOption( self, extend ):
        extend=extend.lower()
        if not ContourExtendOption.valid(extend):
            raise ContourError(tr("Invalid filled contour extend option {0}").format(extend))
        self._extendFilled=extend

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
                raise ContourError(tr("Cannot parse")+" "+zField)
            fields=source.fields()
            context=QgsExpressionContext()
            context.setFields(fields)
            if not expression.prepare(context):
                raise ContourError(tr("Cannot evaluate value")+ " "+zField)
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
                        raise ContourError(tr("Z value {0} is not number")
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
                if discardTolerance > 0:
                    index=ContourUtils.discardDuplicatePoints(
                        x,y,discardTolerance,self.crs().isGeographic())
                    npt1=len(index)
                    if npt1 < npt:
                        x=x[index]
                        y=y[index]
                        z=z[index]
                        feedback.pushInfo(tr("{0} near duplicate points discarded - tolerance {1}")
                                          .format(npt-npt1,discardTolerance))
        except ContourError as ce:
            feedback.reportError(ce.message())
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
            self._gridShape,self._gridOrder=DataGridder(x,y).calcGrid()
            self._gridTested=True
        return self._gridShape is not None

    def gridShape(self):
        return self._gridShape

    def levels( self ):
        if self._levels is None:
            x,y,z = self.data()
            if z is None:
                raise ContourError(tr("Contour data not defined"))
            method=self._contourMethod
            params=self._contourMethodParams
            if method is None:
                raise ContourError(tr("Contouring method not defined"))
            self._levels=ContourMethod.calculateLevels(z,method,**params)
            self._defaultLabelNdp = None
        return self._levels

    def crs( self ):
        return self._source.sourceCrs()

    def wkbtype( self ):
        return ContourType.wkbtype(self._contourType)

    def fields( self ):
        zFieldName=self._zFieldName
        if self._contourType == ContourType.filled:
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

    def contourFeatures(self):
        if self._contourType == ContourType.line:
            return self.lineContourFeatures()
        elif self._contourType == ContourType.filled:
            return self.filledContourFeatures()
        elif self._contourType == ContourType.layer:
            return self.layerContourFeatures()
        else:
            return []

    def gridContourData(self):
        gx,gy,gz=self.data()
        order=self._gridOrder
        shape=self._gridShape
        if order is not None:
            gx=gx[order]
            gy=gy[order]
            gz=gz[order]
        gx=gx.reshape(shape)
        gy=gy.reshape(shape)
        gz=gz.reshape(shape)
        self._feedback.pushInfo("Contouring {0} by {1} grid"
            .format(shape[0],shape[1]))
        return gx, gy, gz

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

    def trigContourData(self):
        x,y,z=self.data()
        self._feedback.pushInfo("Triangulating {0} points"
            .format(len(x)))
        trig=self.buildTriangulation(x,y)
        self._feedback.pushInfo("Contouring {0} triangles"
            .format(trig.triangles.shape[0]))
        return trig,z
        return polygons

    def calcLabelNdp( self ):
        if self._labelNdp is not None and self._labelNdp > 0:
            return self._labelNdp
        if self._defaultLabelNdp is None:
            levels=self.levels()
            ldiff=levels[1:]-levels[:-1]
            try:
                ldmin=np.min(ldiff[ldiff > 0.0])
                # Allow 2dp on minimum increment
                ldmin /= 100
                ndp=0
                while ndp < 10 and ldmin < 1.0:
                    ndp += 1
                    ldmin *= 10.0
            except:
                ndp=4 # Arbitrary!
            self._defaultLabelNdp = ndp
        return self._defaultLabelNdp

    def formatLevel( self, level ):
        ndp=self.calcLabelNdp()
        if ndp < 0:
            return str(level)
        elif self._labelTrimZeros:
            level=np.round(level,ndp)
            return str(level)
        else:
            return "{1:.{0}f}".format(ndp,level)

    def _levelLabel(self,level):
        return self.formatLevel(level)+self._labelUnits

    def lineContourFeatures(self):
        x,y,z=self.data()
        levels = self.levels()
        usegrid=self.isGridded() and self._useGrid
        try:
            if usegrid:
                gx,gy,gz=self.gridContourData()
                cs = contour(gx, gy, gz, levels )
            else:
                trig,z=trigContourData()
                cs = tricontour(trig, z, levels )
        except:
            raise ContourGenerationError.fromException(sys.exc_info())

        fields = self.fields()
        zfield=self._zFieldName
        dx,dy=self._origin
        for i, line in enumerate(cs.collections):
            level=float(cs.levels[i])
            glines = []
            try:
                for path in line.get_paths():
                    if len(path.vertices) > 1:
                        points=[QgsPointXY(x,y) for x,y in path.vertices]
                        glines.append(points)
                geom=QgsGeometry.fromMultiPolylineXY(glines)
                geom.translate(dx,dy)
                feat = QgsFeature(fields)
                feat.setGeometry(geom)
                feat['index']=i
                feat[zfield]=level
                feat['label']=self._levelLabel(level)
                yield feat
            except:
                message=sys.exc_info()[1]
                self._feedback.reportError(message)

    def _rangeLabel(self,min,max):
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
        return lmin+op+lmax+self._labelUnits

    def buildQgsMultipolygon(self,polygon):
        '''
        Construct QgsMultiPolygon from matplotlib version
        '''
        mpoly=[]
        for path in polygon.get_paths():
            path.should_simplify = False
            poly = path.to_polygons()
            if len(poly) < 1:
                continue
            if len(poly[0]) < 3:
                # Have had one vertix polygon from matplotlib!
                continue
            mpoly.append([
                [QgsPointXY(x,y) for x,y in p]
                 for p in poly if len(p) > 3 ])
        if len(mpoly) < 1:
            return None
        geom=QgsGeometry.fromMultiPolygonXY(mpoly)
        geom.makeValid()
        return geom

    def filledContourFeatures(self ):
        levels = self.levels()
        extend=self._extendFilled
        usegrid=self.isGridded() and self._useGrid
        try:
            if usegrid:
                gx,gy,gz=self.gridContourData()
                cs = contourf(gx, gy, gz, levels, extend=extend)
            else:
                trig,z=self.trigContourData()
                cs = tricontourf(trig, z, levels, extend=extend)
        except:
            raise ContourGenerationError.fromException(sys.exc_info())

        levels = [float(l) for l in cs.levels]
        if ContourExtendOption.extendBelow(extend):
            levels = np.append([-np.inf,], levels)
        if ContourExtendOption.extendAbove(extend):
            levels = np.append(levels, [np.inf,])

        fields = self.fields()
        ninvalid=0
        dx,dy=self._origin
        zminfield=self._zFieldName+'_min'
        zmaxfield=self._zFieldName+'_max'

        for i, polygon in enumerate(cs.collections):
            level_min=levels[i]
            level_max=levels[i+1]
            label = self._rangeLabel(level_min,level_max)
            try:
                try:
                    geom=self.buildQgsMultipolygon(polygon)
                    if geom is None:
                        continue
                    geom.translate(dx,dy)
                except Exception as ex:
                    ninvalid += 1
                    continue
                feat = QgsFeature(fields)
                feat.setGeometry(geom)
                feat['index']=i
                feat[zminfield]=level_min
                feat[zmaxfield]=level_max
                feat['label']=label
                yield feat
            except Exception as ex:
                raise
                self._feedback.reportError(sys.exc_info()[1])

        if ninvalid > 0:
            self._feedback.pushInfo(tr('{0} invalid contour geometries discarded').format(ninvalid))

    def layerContourFeatures(self):
        levels = self.levels()
        usegrid=self.isGridded() and self._useGrid
        try:
            if usegrid:
                gx,gy,gz=self.gridContourData()
            else:
                trig,gz=self.trigContourData()
        except:
            raise ContourGenerationError.fromException(sys.exc_info())

        fields = self.fields()
        ninvalid=0
        dx,dy=self._origin
        zfield=self._zFieldName
        zmax=np.max(gz)
        zmax += (1.0+abs(zmax))
        zmin = np.min(gz)

        for i,level in enumerate(levels):
            if level <= zmin:
                continue
            try:
                if usegrid:
                    cs = contourf(gx, gy, gz, [level,zmax], extend=ContourExtendOption.neither)
                else:
                    cs = tricontourf(trig, gz, [level,zmax], extend=ContourExtendOption.neither)
            except:
                raise ContourGenerationError.fromException(sys.exc_info())
            if len(cs.collections) < 1:
                continue
            polygon=cs.collections[0]
            try:
                try:
                    geom=self.buildQgsMultipolygon(polygon)
                    if geom is None:
                        continue
                    geom.translate(dx,dy)
                except Exception as ex:
                    ninvalid += 1
                    # print("Exception:",ex)
                    continue
                feat = QgsFeature(fields)
                feat.setGeometry(geom)
                feat['index']=i
                feat[zfield]=level
                feat['label']=self._levelLabel(level)
                yield feat
            except Exception as ex:
                self._feedback.reportError(ex.message)

        if ninvalid > 0:
            self._feedback.pushInfo(tr('{0} invalid contour geometries discarded').format(ninvalid))

