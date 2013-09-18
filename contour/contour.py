#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#       contour.py
#
#       Copyright 2009 Lionel Roubeyrie <lionel.roubeyrie@gmail.com>
#
#       This program is free software; you can redistribute it and/or modify
#       it under the terms of the GNU General Public License as published by
#       the Free Software Foundation; either version 2 of the License, or
#       (at your option) any later version.
#
#       This program is distributed in the hope that it will be useful,
#       but WITHOUT ANY WARRANTY; without even the implied warranty of
#       MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#       GNU General Public License for more details.
#
#       You should have received a copy of the GNU General Public License
#       along with this program; if not, write to the Free Software
#       Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#       MA 02110-1301, USA.

#  Modified by Chris Crook <ccrook@linz.govt.nz> to contour irregular data


from PyQt4.QtCore import *
from PyQt4.QtGui import *
from qgis.core import *
from qgis.gui import QgsEncodingFileDialog
import resources

import sys
import os.path
import string
import math
import inspect
import numpy as np
import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.mlab import griddata
from shapely.geometry import MultiLineString, MultiPolygon

from frmContour import Ui_ContourDialog

EPSILON = 1.e-27

def _interpolate(a, b, fraction):
    return a + (b - a)*fraction;
    

class Contour:

    def __init__(self, iface):
        self._iface = iface

    def initGui(self):
        self.action = QAction(QIcon(":/plugins/contour/contour.png"), \
        "Contour", self._iface.mainWindow())
        self.action.setWhatsThis("Generate contours based on point vector data")
        QObject.connect(self.action, SIGNAL("triggered()"), self.run)
        self._iface.addToolBarIcon(self.action)
        self._iface.vectorMenu().addAction(self.action)

    def unload(self):
        self._iface.removePluginMenu("&Contour", self.action)
        self._iface.vectorMenu().removeAction(self.action)
        self._iface.removeToolBarIcon(self.action)

    def run(self):
        try:
            dlg = ContourDialog(self._iface)
            dlg.exec_()
        except ContourError:
            QMessageBox.warning(self._iface.mainWindow(), "Contour error",
                str(sys.exc_info()[1]))

###########################################################

class ContourError(Exception):
    def __init__(self, message):
        self._message = message
    def __str__(self):
        return self._message

###########################################################
class ContourDialog(QDialog, Ui_ContourDialog):

    def __init__(self, iface):
        QDialog.__init__(self)
        self._iface = iface
        self._data = None
        self._layer=None
        self._zField = ""
        self._dataIsGrid = False
        self._gridData = None
        self._nr = None
        self._nc = None
        self._gridSaved = False
        self._gridDisplayed = False
        self._zField = ''
        self._loadingLayer = False
        self._contourId = ''
        self._replaceLayerSet = None

        # Set up the user interface from Designer.
        self.setupUi(self)
        self._okButton = self.uButtonBox.button(QDialogButtonBox.Ok)
        self._okButton.setEnabled(False)
        re = QRegExp("\\d+\\.?\\d*(?:[Ee][+-]?\\d+)?")
        self.uLevelsList.setSortingEnabled(False)

        #Signals
        self.uLayerName.currentIndexChanged[int].connect(self.uLayerNameUpdate)
        self.uFieldName.currentIndexChanged['QString'].connect(self.uFieldNameUpdate)
        self.uMinContour.valueChanged[float].connect(self.validMinMax)
        self.uMaxContour.valueChanged[float].connect(self.validMinMax)
        self.uLevelsNumber.valueChanged[int].connect(self.computeLevels)
        self.uLevelsList.itemDoubleClicked[QListWidgetItem].connect(self.validLevel)
        self.uButtonBox.helpRequested.connect(self.showHelp)
        self.uMethod.currentIndexChanged[int].connect(self.changeMethod)
        self.uLinesContours.toggled[bool].connect(self.modeToggled)
        self.uFilledContours.toggled[bool].connect(self.modeToggled)
        self.uBoth.toggled[bool].connect(self.modeToggled)
        self.uLayerContours.toggled[bool].connect(self.modeToggled)

        self.uLevelsNumber.setMinimum(2)
        self.uLevelsNumber.setValue(10)
        self.uLinesContours.setChecked(True)
        self.uExtend.setCurrentIndex(0)
        # populate layer list
        self.progressBar.setValue(0)
        mapCanvas = self._iface.mapCanvas()
        self._loadingLayer = True
        for layer in self.sourceLayers():
            self.uLayerName.addItem(layer.name(),layer)
        self.uLayerName.setCurrentIndex(-1)
        self._loadingLayer = False
        if self.uLayerName.count() <= 0:
            raise ContourError("There are no layers suitable for contouring.\n"+
                              "(That is, point layers with numeric attributes)")
        self.enableOkButton()
        self.setupCurrentLayer( mapCanvas.currentLayer() )
        if self.uLayerName.currentIndex() < 0 and self.uLayerName.count()==1:
            self.uLayerName.setCurrentIndex(0)
        
        # Is MPL version Ok?
        if self._isMPLOk() == False:
            self.message(text="Your matplotlib python module seems to not have the required "+
            "version for using the last contouring algorithms. "+
            "Please note : your points datas must be placed on a regular "+
            "grid before calling this plugin, or update your matplotlib "+
            "module to >= 1.0.0\n", title="Minimum version required")

    def _isGridded(self):
        """
        Check if points data are on a regular grid
        """
        if self._data == None:
            return
        (x, y, z) = self._data
        l = len(x)
        xd=np.diff(x)
        yd=np.diff(y)
        ld = l-1
        ends = np.flatnonzero(xd[0:ld-1]*xd[1:ld]+yd[0:ld-1]*yd[1:ld]<0)+2
        nr = ends[0]
        nc = (len(ends)/2)+1
        ok = True
        if (len(ends) < 2) or (nr*nc != l) or (any(ends%nr > 1)):
           ok = False
        self._nr = nr
        self._nc = nc
        return ok

    def _isMPLOk(self):
        """
        Check if matplotlib version > 1.0.0 for contouring fonctions selection
        """
        version = [int(i) for i in mpl.__version__.split('.')[0:2]]
        return version >= [1, 0]

    def setupCurrentLayer( self, layer ):
        if not layer:
            return
        properties = self.getContourProperties( layer )
        contourId = ''
        sourceLayer = None
        if properties:
            layerId = properties.get('SourceLayerId')
            for l in self.sourceLayers():
                if l.id() == layerId:
                    sourceLayer = l
                    break
            if sourceLayer:
                layer = sourceLayer
                contourId = properties.get('ContourId')
        index = self.uLayerName.findData(layer)
        if index >= 0:
            self.uLayerName.setCurrentIndex(index)
        # If valid existing contour layer, then reset
        if not contourId:
            return
        layerSet = self.contourLayerSet( contourId )
        attr = properties.get('SourceLayerAttr')
        index = self.uFieldName.findText(attr)
        if index < 0:
            return
        try:
            self.uFieldName.setCurrentIndex(index)
            if layerSet.has_key('filled'):
                if layerSet.has_key('lines'):
                    self.uBoth.setChecked(True)
                else:
                    self.uFilledContours.setChecked(True)
            if layerSet.has_key('layers'):
                    self.uLayerContours.setChecked(True)
            else:
                self.uLinesContours.setChecked(True)
            levels = properties.get('Levels').split(';')
            self.uLevelsNumber.setValue(len(levels))
            self.uMinContour.setValue(float(properties.get('MinContour')))
            self.uMaxContour.setValue(float(properties.get('MaxContour')))
            index = self.uMethod.findText(properties.get('Method'))
            if index >= 0:
                self.uMethod.setCurrentIndex(index)
            index = self.uExtend.findText(properties.get('Extend'))
            if index >= 0:
                self.uExtend.setCurrentIndex(index)
            self.uLevelsList.clear()
            for level in levels:
                self.uLevelsList.addItem(level)
            self.uPrecision.setValue(int(properties.get('LabelPrecision')))
        finally:
            pass
        self._replaceLayerSet = layerSet

    def uLayerNameUpdate(self, index):
        if self._loadingLayer:
            return
        self._data = None
        self._replaceLayerSet = None
        self._layer = self.uLayerName.itemData(index)
        self.uLayerDescription.setText("")
        changedLayer = self.getLayerWorkingCopy(self._layer)
        if not changedLayer:
           return
        fieldList = self.getFieldList(changedLayer)
        self.uFieldName.clear()
        self._loadingLayer=True
        for f in fieldList:
            self.uFieldName.addItem(f)

        self.uFieldName.setCurrentIndex(-1)
        self._loadingLayer=False
        if self.uFieldName.count() == 1:
            self.uFieldName.setCurrentIndex(0)
        self.enableOkButton()

    def uFieldNameUpdate(self, inputField):
        if self._loadingLayer:
            return
        self._data = None
        self._replaceLayerSet = None
        if not self._layer:
            return
        self._zField = inputField
        if not self._zField:
            self.enableOkButton()
            return
        x, y, z = self.getData(self._layer, inputField)
        self.z = z
        ndata = len(x)
        self.uMinContour.setValue(np.min(z))
        self.uMaxContour.setValue(np.max(z))
        self.computeLevels()
        self.updateOutputName()
        self.enableOkButton()

    def changeMethod(self, i):
        if self._layer.name() and self._zField:
            self.computeLevels()

    def updateOutputName(self):
        if self._layer.name() and self._zField:
            self.uOutputName.setText("%s_%s"%(self._layer.name(), self._zField))

    def validMinMax(self):
        self.computeLevels()

    def validLevel(self, item):
        val = item.text()
        z = self._data[2]
        newval, ok = QInputDialog.getDouble(self, "Level",
                     "Enter the new level :", float(val),
                     -2147483647, 2147483647, 4)
        if ok:
            item.setText("%.4f"%newval)
            self.enableOkButton()

    def computeLevels(self):
        method = str(self.uMethod.itemText(self.uMethod.currentIndex()))
        if method == "Equal":
            levels = np.linspace(float(self.uMinContour.value()),
                            float(self.uMaxContour.value()),
                            self.uLevelsNumber.value())
        if method == "Quantile": #Copied from scipy.stats.scoreatpercentile
            levels = list()
            values = np.sort(self.z.flatten())
            values = values[(float(self.uMinContour.value()) <= values) & (values <= self.uMaxContour.value())]
            if values.size > 1:
                for per in np.linspace(0, 100, self.uLevelsNumber.value()):
                    idx = per /100. * (values.shape[0] - 1)
                    if (idx % 1 == 0):
                        levels.append(values[idx])
                    else:
                        v = _interpolate(values[int(idx)], values[int(idx) + 1], idx % 1)
                        levels.append(v)

        self.uLevelsList.clear()
        for i in range(0, len(levels)):
            self.uLevelsList.addItem("%.4f"%levels[i])
        self.enableOkButton()

    def modeToggled(self,enabled):
        if enabled:
            self.enableOkButton()

    def enableOkButton(self):
        self._okButton.setEnabled(False)
        try:
            self.validate()
            self._okButton.setEnabled(True)
        except:
            pass

    def confirmReplaceSet(self,set):
        message = "The following layers already have contours of " + self._zField + "\n"
        message = message + "Do you want to replace them with the new contours?\n\n"

        for layer in set.values():
            message = message + "\n   " + layer.name()
        return QMessageBox.question(self,"Replace contour layers",message,
                             QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Cancel)

    def accept(self):
        try:
            self.validate()
            self.validateConditions()
            self._contourId = QDateTime.currentDateTime().toString("yyyyMMddhhmmss")
            replaceContourId = ''
            for set in self.candidateReplacementSets():
                result = self.confirmReplaceSet(set)
                if result == QMessageBox.Cancel:
                    return
                if result == QMessageBox.Yes:
                    self._replaceLayerSet = set
                    replaceContourId = self.layerSetContourId(set)
                    break
            if self.uLinesContours.isChecked():
                self.makeContours()
            elif self.uFilledContours.isChecked():
                self.makeFilledContours()
            elif self.uBoth.isChecked():
                self.makeFilledContours()
                self.makeContours()
            elif self.uLayerContours.isChecked():
                self.makeFilledContours(True)
            oldLayerSet = self.contourLayerSet( replaceContourId )
            if oldLayerSet:
                for layer in oldLayerSet.values():
                    QgsMapLayerRegistry.instance().removeMapLayer( layer.id() )
            self._replaceLayerSet = self.contourLayerSet(self._contourId)

        except ContourError:
            self.message("Error calculating grid/contours: "+str(sys.exc_info()[1]))
        except:
            self.message("Exception struck: " + str(sys.exc_info()[1]))
            raise
        # self._okButton.setEnabled(False)

    def message(self,text,title="Contour Error"):
        QMessageBox.warning(self, title, text)

    def showHelp(self):
        file = inspect.getsourcefile(ContourDialog)
        file = 'file://' + os.path.join(os.path.dirname(file),'index.html')
        file = file.replace("\\","/")
        self._iface.openURL(file,False)

    def validate(self):
        message = None
        if self.uLayerName.currentText() == "":
            message = "Please specify vector layer"
        if (self.uFieldName.currentText() == "") or (self._data == None):
            message = "Please specify data field"
        if message != None:
            raise ContourError(message)

    def validateConditions(self):
        if (self._isMPLOk() == False) and (self._isGridded() == False):
            message = "This layer does not have a regular data grid and your matplotlib module is not suitable to compute contouring"
            raise ContourError(message)
    #############################################################################
    # Contour calculation code

    def sourceLayers(self):
        for layer in QgsMapLayerRegistry.instance().mapLayers().values():
            if (layer.type() == layer.VectorLayer) and (layer.geometryType() == QGis.Point):
                if self.getFieldList(layer):
                    yield layer

    def getFieldList(self, vlayer):
        numberfields = []
        for f in vlayer.pendingFields():
            typ = unicode(f.typeName())[0:3].lower()
            if typ=='int' or typ=='dou' or typ=='rea':
                numberfields.append(unicode(f.name()))
        return numberfields

    def getLevels(self):
        list = self.uLevelsList
        return [float(list.item(i).text()) for i in range(0, list.count())]

    def clearLayer(self, layer):
        pl = layer.dataProvider()
        request = QgsFeatureRequest()
        request.setFlags(QgsFeatureRequest.NoGeometry)
        request.setSubsetOfAttributes([])
        fids = []
        for f in pl.getFeatures(request):
            fids.append(f.id())
        pl.deleteFeatures(fids)
        pl.deleteAttributes(pl.attributeIndexes())
        layer.updateFields()

    def createLayer( self, source, name, provider ):
        # Need to avoid prompting for CRS when creating a vector layer.
        settings = QSettings()
        prjSetting = settings.value("/Projections/defaultBehaviour")
        layer = None
        try:
            settings.setValue("/Projections/defaultBehaviour", '')
            layer = QgsVectorLayer(source, name, provider)
        finally:
            if prjSetting:
                settings.setValue("/Projections/defaultBehaviour", prjSetting)
        return layer

    def createVectorLayer(self, type, name, mode,fields):
        layer = None
        if self._replaceLayerSet:
            layer = self._replaceLayerSet.get(mode)

        if layer:
            self.clearLayer(layer)
        else:
            layer = self.createLayer(type, name, "memory")

        if not layer:
            raise ContourError("Could not create layer for contours")

        attributes = [
            QgsField(name,QVariant.Int,'Int') if ftype == int else
            QgsField(name,QVariant.Double,'Double') if ftype == float else
            QgsField(name,QVariant.String,'String')
            for name, ftype in fields
        ]
        pr = layer.dataProvider()
        pr.addAttributes( attributes )
        layer.updateFields()

        layer.setCrs(self._crs, False)
        levels = ";".join(map(str, self.getLevels()))
        properties = {
            'ContourId' : self._contourId,
            'SourceLayerId' : self._layer.id(),
            'SourceLayerAttr' : self._zField,
            'Mode' : mode,
            'Levels' : levels,
            'LabelPrecision' : str(self.uPrecision.value()),
            'MinContour' : str(self.uMinContour.value()),
            'MaxContour' : str(self.uMaxContour.value()),
            'Extend' : str(self.uExtend.itemText(self.uExtend.currentIndex())),
            'Method' : str(self.uMethod.itemText(self.uMethod.currentIndex()))
            }
        self.setContourProperties(layer, properties)
        return layer

    def addLayer(self, layer):
        registry = QgsMapLayerRegistry.instance()
        if not registry.mapLayer(layer.id()):
            registry.addMapLayer(layer)
        else:
            self._iface.legendInterface().setLayerVisible(layer, True)
            layer.setCacheImage(None)
            self._iface.mapCanvas().refresh()

    def setContourProperties( self, layer, properties ):
        for key in properties.keys():
            layer.setCustomProperty('ContourPlugin.'+key, properties[key])

    def getContourProperties( self, layer ):
        if layer.type() != layer.VectorLayer or layer.dataProvider().name() != "memory":
            return None
        properties = {}
        for key in [
            'ContourId',
            'SourceLayerId',
            'SourceLayerAttr',
            'Mode',
            'Levels',
            'LabelPrecision',
            'MinContour',
            'MaxContour',
            'Extend',
            'Method'
            ]:
            properties[key] = str(layer.customProperty('ContourPlugin.'+key))
        if not properties['ContourId']:
            return None
        return properties

    def contourLayers(self, wanted={}):
        for layer in QgsMapLayerRegistry.instance().mapLayers().values():
            properties = self.getContourProperties(layer)
            if not properties:
                continue
            ok = True
            for key in wanted.keys():
                if properties.get(key) != wanted[key]:
                    ok = False
                    break
            if ok:
                yield layer

    def contourLayerSet( self, contourId ):
        layers = self.contourLayers({'ContourId':contourId} )
        layerSet={}
        for layer in layers:
            properties = self.getContourProperties(layer)
            layerSet[properties.get('Mode')] = layer
        return layerSet

    def layerSetContourId( self, layerSet ):
        if layerSet:
            return self.getContourProperties(layerSet.values()[0]).get('ContourId')
        return None

    def candidateReplacementSets( self ):
        # Note: use _replaceLayerSet first as this will be the layer
        # set that the contour dialog was opened with. Following this
        # look for any other potential layers.
        ids = []
        if self._replaceLayerSet:
            set = self._replaceLayerSet
            self._replaceLayerSet = None
            ids.append(self.layerSetContourId(set))
            yield set

        for layer in self.contourLayers({
            'SourceLayerId' : self._layer.id(),
            'SourceLayerAttr' : self._zField } ):
            id = self.getContourProperties(layer).get('ContourId')
            if id in ids:
                continue
            ids.append(id)
            yield self.contourLayerSet(id)

    def makeContours(self):
        lines = self.computeContours()
        clayer =  self.buildContourLayer(lines)
        self.addLayer(clayer)

    def makeFilledContours(self, asLayers=False):
        polygons = self.computeFilledContours( asLayers )
        if asLayers:
            clayer = self.buildLayeredContourLayer(polygons)
        else:
            clayer = self.buildFilledContourLayer(polygons)
        self.addLayer(clayer)

    def getData(self, layer, zField):
        self._gridData = None
        inLayer = self.getLayerWorkingCopy(layer)
        self._crs = inLayer.crs()

        request = QgsFeatureRequest()
        request.setSubsetOfAttributes([zField], layer.pendingFields() )

        self.progressBar.setRange(0, layer.featureCount())
        count = 0
        x = list()
        y = list()
        z = list()
        for feat in layer.getFeatures( request ):
            zval = feat[zField]
            if isinstance(zval,float):
                geom = feat.geometry().asPoint()
                x.append(geom.x())
                y.append(geom.y())
                z.append(zval)
            count = count + 1
            self.progressBar.setValue(count)
        self.progressBar.setValue(0)
        x = np.array(x)
        y = np.array(y)
        z = np.array(z)
        self._data = [x, y, z]
        return x, y, z

    def computeContours(self):
        extend = str(self.uExtend.itemText(self.uExtend.currentIndex()))
        x, y, z = self._data
        levels = self.getLevels()
        if self._isMPLOk()==True: # If so, we can use the new tricontour fonction
            cs = plt.tricontour(x, y, z, levels, extend=extend)
        else:
            gx = x.reshape(self._nr,self._nc)
            gy = y.reshape(self._nr,self._nc)
            gz = z.reshape(self._nr,self._nc)
            cs = plt.contour(gx, gy, gz, levels, extend=extend)
        lines = list()
        levels = [float(l) for l in cs.levels]
        self.progressBar.setRange(0, len(cs.collections))
        for i, line in enumerate(cs.collections):
            linestrings = []
            for path in line.get_paths():
                if len(path.vertices) > 1:
                    linestrings.append(path.vertices)
            lines.append([ i, levels[i], linestrings])
            self.progressBar.setValue(i+1)
        self.progressBar.setValue(0)
        return lines

    def computeFilledContours(self,asLayers=False):
        levels = self.getLevels()
        polygons = list()
        if asLayers:
            maxvalue=np.max(self._data[2])+1000
            for l in levels:
                self._computeFilledContoursForLevel([l,maxvalue],'none',polygons,True)
        else:
            extend = str(self.uExtend.itemText(self.uExtend.currentIndex()))
            self._computeFilledContoursForLevel(levels,extend,polygons)
        return polygons

    
    def _computeFilledContoursForLevel(self,levels,extend,polygons,oneLevelOnly=False):
        x, y, z = self._data
        if self._isMPLOk()==True: # If so, we can use the new tricontour fonction
            cs = plt.tricontourf(x, y, z, levels, extend=extend)
        else:
            gx = x.reshape(self._nr,self._nc)
            gy = y.reshape(self._nr,self._nc)
            gz = z.reshape(self._nr,self._nc)
            cs = plt.contourf(gx, gy, gz, levels, extend=extend)
        levels = [float(l) for l in cs.levels]
        if extend=='min' or extend=='both':
            levels = np.append([-np.inf,], levels)
        if extend=='max' or extend=='both':
            levels = np.append(levels, [np.inf,])
        # self.progressBar.setRange(0, len(cs.collections))
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
                    exterior = np.vstack((exterior, self.epsi_point(p0), self.epsi_point(p0)))
                    if len(poly)>1: #There's some holes
                        for h in poly[1:]:
                            if len(h)>2:
                                holes.append(h)

                mpoly.append([exterior, holes])
            if len(mpoly) > 0:
                polygons.append([i, levels[i], levels[i+1], mpoly])
            if oneLevelOnly:
                break
            #self.progressBar.setValue(i+1)
        # self.progressBar.setValue(0)

    def epsi_point(self, point):
        x = point[0] + EPSILON*np.random.random()
        y = point[1] + EPSILON*np.random.random()
        return [x, y]

    def buildContourLayer(self, lines):
        dec = self.uPrecision.value()
        name = "%s"%str(self.uOutputName.text())
        zfield=self._zField
        vl = self.createVectorLayer("MultiLineString", name, 'lines',
                                   [('index',int),
                                    (zfield,float),
                                    ('label',str)
                                   ])
        pr = vl.dataProvider()
        fields=pr.fields()
        msg = list()
        for i, level, line in lines:
            levels=str(np.round(level,dec))
            try:
                feat = QgsFeature(fields)
                feat.setGeometry(QgsGeometry.fromWkt(MultiLineString(line).to_wkt()))
                feat['index']=i
                feat[zfield]=level
                feat['label']=levels
                pr.addFeatures( [ feat ] )
            except:
                msg.append(str(sys.exc_info()[1]))
                msg.append(levels)
        if len(msg) > 0:
            self.message("Levels not represented : %s"%", ".join(msg),"Contour issue")
        vl.updateExtents()
        vl.commitChanges()
        return vl

    def buildFilledContourLayer(self, polygons, asLayers=False):
        dec = self.uPrecision.value()
        name = "%s"%str(self.uOutputName.text())
        zField = self._zField
        zmin=zField+'_min'
        zmax=zField+'_max'
        vl = self.createVectorLayer("MultiPolygon", name, 'filled',
                                   [('index',int),
                                    (zmin,float),
                                    (zmax,float),
                                    ('label',str)
                                   ])
        pr = vl.dataProvider()
        fields = pr.fields()
        msg = list()
        for i, level_min, level_max, polygon in polygons:
            levels = "%s - %s"%(np.round(level_min, dec), np.round(level_max, dec))
            try:
                feat = QgsFeature(fields)
                try:
                    feat.setGeometry(QgsGeometry.fromWkt(MultiPolygon(polygon).to_wkt()))
                except:
                    continue
                feat['index']=i
                feat[zmin]=level_min
                feat[zmax]=level_max
                feat['label']=levels
                pr.addFeatures( [ feat ] )
            except:
                self.message(str(sys.exc_info()[1]))
                msg.append("%s"%levels)
        if len(msg) > 0:
            self.message("Levels not represented : %s"%", ".join(msg),"Filled Contour issue")
        vl.updateExtents()
        vl.commitChanges()
        return vl

    def buildLayeredContourLayer(self, polygons, asLayers=False):
        dec = self.uPrecision.value()
        name = "%s"%str(self.uOutputName.text())
        zfield = self._zField
        vl = self.createVectorLayer("MultiPolygon", name, 'layers',
                                   [('index',int),
                                    (zfield,float),
                                    ('label',str)
                                   ])
        pr = vl.dataProvider()
        fields = pr.fields()
        msg = list()
        for i, level_min, level_max, polygon in polygons:
            levels = "%s"%(np.round(level_min, dec))
            try:
                feat = QgsFeature(fields)
                try:
                    feat.setGeometry(QgsGeometry.fromWkt(MultiPolygon(polygon).to_wkt()))
                except:
                    continue
                feat['index']=i
                feat[zfield]=level_min
                feat['label']=levels
                pr.addFeatures( [ feat ] )
            except:
                self.message(str(sys.exc_info()[1]))
                msg.append(levels)
        if len(msg) > 0:
            self.message("Levels not represented : %s"%", ".join(msg),"Layered Contour issue")
        vl.updateExtents()
        vl.commitChanges()
        return vl

    def getLayerWorkingCopy(self, layer):
        ''' Gets a copy of the map layer to provide an independent provider '''
        vlayer = layer
        if layer.dataProvider().name() != "memory":
            vlayer = self.createLayer(layer.source(),  layer.name(),  layer.dataProvider().name())
        if vlayer and vlayer.isValid():
            return vlayer
        else:
            self.message("Vector layer is not valid")

