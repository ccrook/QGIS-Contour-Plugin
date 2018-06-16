#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#       contour.py
#
#       Copyright 2018 Chris Crook <ccrook@linz.govt.nz>
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

from PyQt5.QtCore import *
from PyQt5.QtWidgets import *
from PyQt5.QtGui import *
from PyQt5.QtXml import QDomDocument
from qgis.core import *
from qgis.gui import QgsMessageBar
from . import resources
from . import ContourMethod
from .ContourMethod import ContourMethodError
from .ContourGenerator import ContourGenerator, ContourType, ContourExtendOption

import sys
import os.path
import string
import math
import re
import inspect

mplAvailable=True
try:
    import numpy as np
    import matplotlib as mpl
    import matplotlib.pyplot as plt
    from matplotlib.mlab import griddata
except ImportError:
    mplAvailable=False

from .ContourDialogUi import Ui_ContourDialog

EPSILON = 1.e-27
LINES='lines'
FILLED='filled'
BOTH='both'
LAYERS='layer'

def tr(string):
    return QCoreApplication.translate('Processing', string)

class ContourDialogPlugin:

    def __init__(self, iface):
        self._iface = iface

    def initGui(self):
        if not mplAvailable:
            QMessageBox.warning(self._iface.mainWindow(), tr("Contour error"),
                tr("The contour plugin is disabled as it requires python modules"
                " numpy and matplotlib which are not both installed"))
            return

        self.action = QAction(QIcon(":/plugins/contour/contour.png"), \
        "Contour", self._iface.mainWindow())
        self.action.setWhatsThis(tr("Generate contours based on point vector data"))
        self.action.triggered.connect(self.run)
        self._iface.addToolBarIcon(self.action)
        self._iface.vectorMenu().addAction(self.action)

    def unload(self):
        try:
            self._iface.removePluginMenu("&Contour", self.action)
            self._iface.vectorMenu().removeAction(self.action)
            self._iface.removeToolBarIcon(self.action)
        except:
            pass

    def run(self):
        try:
            dlg = ContourDialog(self._iface)
            dlg.exec_()
        except ContourError:
            QMessageBox.warning(self._iface.mainWindow(), tr("Contour error"),
                str(sys.exc_info()[1]))

###########################################################

class ContourError(RuntimeError):
    pass

class ContourGenerationError(ContourError):
    pass

###########################################################

class ContourDialog(QDialog, Ui_ContourDialog):

    class Feedback:

        def __init__( self, messagebar, progress ):
            self._messageBar=messagebar
            self._progress=progress

        def isCanceled( self ):
            return False

        def setProgress( self, percent ):
            if self._progress:
                self._progress.setValue(percent)

        def pushInfo( self, info ):
            self._messageBar.pushInfo('',info)

        def reportError( self, message, fatal=False ):
            self._messageBar.pushWarning(tr('Error') if fatal else tr('Warning'),message)

    def __init__(self, iface):
        QDialog.__init__(self)
        self._iface = iface
        self._origin = None
        self._loadedDataDef = None
        self._layer=None
        self._zField = ''
        self._loadingLayer = False
        self._contourId = ''
        self._replaceLayerSet = None
        self._canEditList = False

        # Set up the user interface from Designer.
        self.setupUi(self)

        self.uAddButton.setEnabled(False)
        #re = QRegExp("\\d+\\.?\\d*(?:[Ee][+-]?\\d+)?")
        self.uLevelsList.setSortingEnabled(False)
        self.uSelectedOnly.setChecked(False)
        self.uSelectedOnly.setEnabled(False)
        self.uUseGrid.setEnabled(False)
        self.uSourceLayer.setFilters(QgsMapLayerProxyModel.PointLayer)
        self.uDataField.setExpressionDialogTitle(tr("Value to contour"))
        self.uDataField.setFilters(QgsFieldProxyModel.Numeric)
        self.uNContour.setMinimum(2)
        self.uNContour.setValue(10)
        self.uSetMinimum.setChecked(False)
        self.uMinContour.setEnabled(False)
        self.uSetMaximum.setChecked(False)
        self.uMaxContour.setEnabled(False)
        self.uLinesContours.setChecked(True)
        self.uExtend.setCurrentIndex(0)
        self.uExtend.setEnabled(False)
        self.progressBar.setValue(0)
        for method in ContourMethod.methods:
            self.uMethod.addItem(method.name,method.id)
        for option in ContourExtendOption.options():
            self.uExtend.addItem(ContourExtendOption.description(option),option)

        self._feedback=ContourDialog.Feedback(self.uMessageBar,self.progressBar)
        self._generator=ContourGenerator(feedback=self._feedback)

        self.loadSettings()

        mapCanvas = self._iface.mapCanvas()
        self.enableContourParams()
        self.enableOkButton()

        #Signals
        self.uSourceLayer.layerChanged.connect(self.uSourceLayerChanged )
        self.uDataField.fieldChanged['QString'].connect(self.uDataFieldUpdate)
        self.uSelectedOnly.toggled.connect(self.reloadData)
        self.uUseGrid.toggled.connect(self._generator.setUseGrid)
        self.uThinPoints.toggled.connect(self.reloadData)
        self.uThinRadius.valueChanged[float].connect(self.reloadData)
        self.uContourInterval.valueChanged[float].connect(self.computeLevels)
        self.uSetMinimum.toggled[bool].connect(self.toggleSetMinimum)
        self.uSetMaximum.toggled[bool].connect(self.toggleSetMaximum)
        self.uMinContour.valueChanged[float].connect(self.computeLevels)
        self.uMaxContour.valueChanged[float].connect(self.computeLevels)
        self.uNContour.valueChanged[int].connect(self.computeLevels)
        self.uPrecision.valueChanged[int].connect(self.updatePrecision)
        self.uTrimZeroes.toggled[bool].connect(self.updatePrecision)
        self.uLevelsList.itemClicked[QListWidgetItem].connect(self.editLevel)
        self.uHelpButton.clicked.connect(self.showHelp)
        self.uAddButton.clicked.connect(self.addContours)
        self.uCloseButton.clicked.connect(self.closeDialog)
        self.uMethod.currentIndexChanged[int].connect(self.computeLevels)
        self.uMethod.currentIndexChanged[int].connect(self.enableContourParams)
        self.uLinesContours.toggled[bool].connect(self.modeToggled)
        self.uFilledContours.toggled[bool].connect(self.modeToggled)
        self.uBoth.toggled[bool].connect(self.modeToggled)
        self.uLayerContours.toggled[bool].connect(self.modeToggled)

        # populate layer list
        if self.uSourceLayer.count() <= 0:
            raise ContourError(tr("There are no point geometry layers suitable for contouring"))
        self.setupCurrentLayer( mapCanvas.currentLayer() )
        if self.uSourceLayer.currentIndex() < 0 and self.uSourceLayer.count()==1:
            self.uSourceLayer.setCurrentIndex(0)
        self.uSourceLayerChanged(self.uSourceLayer.currentLayer())
        
        # Is MPL version Ok?
        if self._isMPLOk() == False:
            self.warnUser(tr("You are using an old version matplotlib - only gridded data is supported"))

    def warnUser(self,message):
        self._feedback.reportError(message)

    def adviseUser(self,message):
        self._feedback.pushInfo(message)

    def closeDialog(self):
        self.saveSettings()
        self.close()

    def _isMPLOk(self):
        """
        Check if matplotlib version > 1.0.0 for contouring fonctions selection
        """
        version = [int(i) for i in mpl.__version__.split('.')[0:2]]
        return version >= [1, 0]

    def updatePrecision( self, ndp ):
        ndp=self.uPrecision.value()
        self.uMinContour.setDecimals( ndp )
        self.uMaxContour.setDecimals( ndp )
        x,y,z=self._generator.data()
        if z is not None:
            self.uMinContour.setValue(np.min(z))
            self.uMaxContour.setValue(np.max(z))
            self.showLevels()

    def _getOptionalValue( self, properties, name, typefunc ):
        fval=properties.get(name,'')
        if fval != '':
            try:
                return typefunc(fval)
            except:
                pass
        return None

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
        index = self.uSourceLayer.setLayer(layer)
        # If valid existing contour layer, then reset
        if not contourId:
            return
        layerSet = self.contourLayerSet( contourId )
        try:
            attr = properties.get('SourceLayerAttr')
            self.uDataField.setField(attr)
            if FILLED in layerSet:
                if LINES in layerSet:
                    self.uBoth.setChecked(True)
                else:
                    self.uFilledContours.setChecked(True)
            elif LAYERS in layerSet:
                    self.uLayerContours.setChecked(True)
            else:
                self.uLinesContours.setChecked(True)
            index = self.uMethod.findData(properties.get('Method'))
            if index >= 0:
                self.uMethod.setCurrentIndex(index)
            index = self.uExtend.findData(properties.get('Extend'))
            if index >= 0:
                self.uExtend.setCurrentIndex(index)
            self.uExtend.setEnabled(self.uFilledContours.isChecked() or self.uBoth.isChecked())
            self.uPrecision.setValue(int(properties.get('LabelPrecision')))
            self.uTrimZeroes.setChecked(properties.get('TrimZeroes') == 'yes' )
            self.uLabelUnits.setText(properties.get('LabelUnits') or '')
            self.uApplyColors.setChecked( properties.get('ApplyColors') == 'yes' )
            ramp=self.stringToColorRamp( properties.get('ColorRamp'))
            if ramp:
                self.uColorRamp.setColorRamp(ramp)
            self.uReverseRamp.setChecked( properties.get('ReverseRamp') == 'yes' )
            fval=self._getOptionalValue(properties,'MinContour',float)
            self.uSetMinimum.setChecked( fval is not None )
            if fval is not None:
                self.uMinContour.setValue(fval)
            fval=self._getOptionalValue(properties,'MaxContour',float)
            self.uSetMaximum.setChecked( fval is not None )
            if fval is not None:
                self.uMaxContour.setValue(fval)
            levels = properties.get('Levels').split(';')
            ival=self._getOptionalValue(properties,'NContour',int)
            if ival is not None:
                self.uNContour.setValue(ival)
            self.uLevelsList.clear()
            for level in levels:
                self.uLevelsList.addItem(level)
            fval=self._getOptionalValue(properties,'Interval',float)
            if fval is not None:
                self.uContourInterval.setValue(fval)
        finally:
            pass
        self._replaceLayerSet = layerSet

    def uSourceLayerChanged(self, layer):
        if self._loadingLayer:
            return
        self._replaceLayerSet = None
        self._layer = layer
        self.uLayerDescription.setText("")
        self.uDataField.setLayer(layer)
        if layer is not None:
            try:

                # Get a default resolution for point thinning
                extent=self._layer.extent()
                self._loadingLayer=True
                haveSelected=self._layer.selectedFeatureCount() > 0
                self.uSelectedOnly.setChecked(haveSelected)
                self.uSelectedOnly.setEnabled(haveSelected)
            finally:
                self._loadingLayer=False
        self.enableOkButton()

    def uDataFieldUpdate(self, inputField):
        self._zField,isExpression,isValid = self.uDataField.currentField()
        self.reloadData()

    def dataChanged( self ):
        x,y,z=self._generator.data()
        if z is not None:
            zmin=np.min(z)
            zmax=np.max(z)
            ndp=self.uPrecision.value()
            if zmax-zmin > 0:
                ndp2=ndp
                while 10**(-ndp2) > (zmax-zmin)/100 and ndp2 < 10:
                    ndp2 += 1
                if ndp2 != ndp:
                    self.uPrecision.setValue(ndp2)
                    self.adviseUser(tr("Resetting the label precision to match range of data values"))
            if not self.uSetMinimum.isChecked():
                self.uMinContour.setValue(zmin)
            if not self.uSetMaximum.isChecked():
                self.uMaxContour.setValue(zmax)
            gridded=self._generator.isGridded()
            self.uUseGrid.setEnabled(gridded)
            self.uUseGrid.setChecked(gridded)
            self.uUseGridLabel.setEnabled(gridded)
            description=tr('Contouring {0} points').format(len(z))
            if gridshape is not None:
                description=description+tr(' in a {0} x {1} grid').format(*gridshape)
            else:
                description=description+' ('+tr('not in regular grid')+')'
            self.uLayerDescription.setText(description)
        else:
            self.uLayerDescription.setText(tr("No data selected for contouring"))

    def reloadData(self):
        if self._loadingLayer:
            return
        self._loadingLayer=True
        try:
            fids=None
            if self._layer is not None and self.uSelectedOnly.isChecked():
                fids=self._layer.selectedFeatureIds()
            self._generator.setDataSource( self._layer, self._zField, fids )
            duptol=0.0
            if self.uThinPoints.isChecked():
                duptol=self.uThinRadius.value()
            self._generator.setDuplicatePointTolerance(duptol)
            self.dataChanged()
        finally:
            self._loadingLayer=False
        self._replaceLayerSet = None
        if not self._layer or not self._zField:
            self.enableOkButton()
            return
        self.computeLevels()
        self.updateOutputName()
        self.enableOkButton()

    def updateOutputName(self):
        if self._layer.name() and self._zField:
            zf=self._zField
            if re.search(r'\W',zf):
                zf='expr'
            self.uOutputName.setText("%s_%s"%(self._layer.name(), zf ))

    def editLevel(self, item=None):
        if not self._canEditList:
            return
        if item is None or QApplication.keyboardModifiers() & Qt.ShiftModifier:
            list = self.uLevelsList
            val=' '.join([list.item(i).text() for i in range(0, list.count())])
        else:
            val = item.text()
        newval, ok = QInputDialog.getText(self, tr("Update level"), 
                         tr("Enter a single level to replace this one")+"\n"+
                         tr("or a space separated list of levels to replace all"),
                         QLineEdit.Normal,
                         val)
        if ok:
            values=newval.split()
            fval=[]
            for v in values:
                try:
                    fval.append(float(v))
                except:
                    QMessageBox.warning(self._iface.mainWindow(), tr("Contour error"),
                                        tr("Invalid contour value {0}").format(v))
                    return
            if len(values) < 1:
                return
            if len(values) == 1: 
                item.setText(newval)
                self.enableOkButton()
            else:
                values.sort(key=float)
                index=self.uMethod.findData('manual')
                if index >= 0:
                    self.uMethod.setCurrentIndex(index)
                self.uNContour.setValue(len(values))
                self.uLevelsList.clear()
                for v in values:
                    self.uLevelsList.addItem(v)

            fval=self.getLevels()
            self._generator.setContourLevels(fval)
            self.enableOkButton()

    def getMethod( self ):
        index=self.uMethod.currentIndex()
        methodid=self.uMethod.itemData(index)
        return ContourMethod.getMethod(methodid)

    def contourLevelParams( self ):
        method=self.getMethod()
        ncontour=self.uNContour.value()
        interval=self.uContourInterval.value()
        zmin=None
        zmax=None
        if self.uSetMinimum.isChecked():
            zmin=self.uMinContour.value()
        if self.uSetMaximum.isChecked():
            zmax=self.uMaxContour.value()
        list=self.uLevelsList
        levels=' '.join([list.item(i).text() for i in range(0, list.count())])
        params={
            'min': zmin,
            'max': zmax,
            'interval': interval,
            'ncontour': ncontour,
            'maxcontour': ncontour,
            'mantissa': None,
            'levels': levels
            }
        return method.id, params

    def enableContourParams( self ):
        method=self.getMethod()
        params=[]
        if method is not None:
            params=list(method.required)
            params.extend(method.optional)
        print(params,method.required,method.optional)
        self.uContourInterval.setEnabled( 'interval' in params )
        self.uNContour.setEnabled( 'ncontour' in params or 'maxcontour' in params )
        self.uSetMinimum.setEnabled( 'min' in params )
        self.uMinContour.setEnabled( 'min' in params and self.uSetMinimum.isChecked() )
        self.uSetMaximum.setEnabled( 'max' in params )
        self.uMaxContour.setEnabled( 'max' in params and self.uSetMaximum.isChecked() )
        self._canEditList='levels' in params

    def toggleSetMinimum( self ):
        self.uMinContour.setEnabled(self.uSetMinimum.isChecked())
        if not self.uSetMinimum.isChecked():
            x,y,z = self._generator.data()
            if z is not None:
                self.uMinContour.setValue(np.min(z))
                self.computeLevels()

    def toggleSetMaximum( self ):
        self.uMaxContour.setEnabled(self.uSetMaximum.isChecked())
        if not self.uSetMaximum.isChecked():
            x,y,z = self._generator.data()
            if z is not None:
                self.uMaxContour.setValue(np.max(z))
                self.computeLevels()

    def computeLevels(self):
        # Use ContourGenerator code
        methodcode,params=self.contourLevelParams()
        self._generator.setContourMethod(methodcode,params)
        self.showLevels()
        self.enableOkButton()

    def showLevels(self):
        self.uLevelsList.clear()
        try:
            levels=self._generator.levels()
            # Need to create some contours if manual and none
            # defined
            if self._canEditList and len(levels) == 0:
                x,y,z=self._generator.data()
                if z is not None:
                    ncontour=self.uNContour.value()
                    try:
                        levels=ContourMethod.calculateLevels(z,'equal',ncontour=ncontour)
                    except:
                        levels=[0.0]
        except (ContourMethodError,ContourError) as ex:
            self._feedback.pushInfo(ex.message())
            return
        for i in range(0, len(levels)):
            self.uLevelsList.addItem(self.formatLevel(levels[i]))

    def modeToggled(self,enabled):
        if enabled:
            self.uExtend.setEnabled(self.uFilledContours.isChecked() or self.uBoth.isChecked())
            self.enableOkButton()

    def enableOkButton(self):
        self.uAddButton.setEnabled(False)
        try:
            self.validate()
            self.uAddButton.setEnabled(True)
        except:
            pass

    def confirmReplaceSet(self,set):
        message = (tr("The following layers already have contours of {0}").format(self._zField) + "\n"
                    + tr("Do you want to replace them with the new contours?")+"\n\n")

        for layer in list(set.values()):
            message = message + "\n   " + layer.name()
        return QMessageBox.question(self,tr("Replace contour layers"),message,
                             QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Cancel)

    def addContours(self):
        try:
            self.validate()
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
            try:
                QApplication.setOverrideCursor(QCursor(Qt.WaitCursor))
                self.setLabelFormat()
                if self.uLinesContours.isChecked() or self.uBoth.isChecked():
                    self.makeContourLayer(ContourType.line)
                if self.uFilledContours.isChecked() or self.uBoth.isChecked():
                    self.makeContourLayer(ContourType.filled)
                if self.uLayerContours.isChecked():
                    self.makeContourLayer(ContourType.layer)
                oldLayerSet = self.contourLayerSet( replaceContourId )
                if oldLayerSet:
                    for layer in list(oldLayerSet.values()):
                        QgsProject.instance().removeMapLayer( layer.id() )
                self._replaceLayerSet = self.contourLayerSet(self._contourId)
            finally:
                QApplication.restoreOverrideCursor()

        except ContourGenerationError as cge:
            self.warnUser(tr("Exception encountered: ") + str(cge) +" "+tr("(Try removing duplicate points)"))
        except ContourError as ce:
            self.warnUser(tr("Error calculating grid/contours: {0}").format(ce))
        # self.uAddButton.setEnabled(False)

    def showHelp(self):
        file = os.path.realpath(__file__)
        file = os.path.join(os.path.dirname(file),'doc','ContourDialog.html')
        QDesktopServices.openUrl(QUrl.fromLocalFile(file))

    def validate(self):
        message = None
        if self.uSourceLayer.currentLayer() is None:
            message = tr("Please specify vector layer")
        if (self.uDataField.currentText() == ""):
            message = tr("Please specify data field")
        if message != None:
            raise ContourError(message)

    def sourceLayers(self):
        for layer in list(QgsProject.instance().mapLayers().values()):
            if (layer.type() == layer.VectorLayer) and (layer.geometryType() == QgsWkbTypes.PointGeometry):
                yield layer

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

    def createVectorLayer(self, type, name, mode,fields,crs):
        layer = None
        if self._replaceLayerSet:
            layer = self._replaceLayerSet.get(mode)

        if layer:
            self.clearLayer(layer)
        else:
            url=QgsWkbTypes.displayString(type)+'?crs=internal:'+str(crs.srsid())
            layer = QgsVectorLayer(url, name, "memory")

        if layer is None:
            raise ContourError(tr("Could not create layer for contours"))

        pr = layer.dataProvider()
        pr.addAttributes( fields )
        layer.updateFields()

        layer.setCrs(crs, False)
        levels = ";".join(map(str, self.getLevels()))
        properties = {
            'ContourId' : self._contourId,
            'SourceLayerId' : self._layer.id(),
            'SourceLayerAttr' : self._zField,
            'Mode' : mode,
            'Levels' : levels,
            'LabelPrecision' : str(self.uPrecision.value()),
            'TrimZeroes' : 'yes' if self.uTrimZeroes.isChecked() else 'no',
            'LabelUnits' : str(self.uLabelUnits.text()),
            'NContour' : str(self.uNContour.value()),
            'MinContour' : str(self.uMinContour.value()) if self.uSetMinimum.isChecked() else '',
            'MaxContour' : str(self.uMaxContour.value()) if self.uSetMaximum.isChecked() else '',
            'Extend' : self.uExtend.itemData(self.uExtend.currentIndex()),
            'Method' : self.uMethod.itemData(self.uMethod.currentIndex()),
            'ApplyColors' : 'yes' if self.uApplyColors.isChecked() else 'no',
            'ColorRamp' : self.colorRampToString( self.uColorRamp.colorRamp()),
            'ReverseRamp' : 'yes' if self.uReverseRamp.isChecked() else 'no',
            'ContourInterval' : str(self.uContourInterval.value()),
            }
        self.setContourProperties(layer, properties)
        return layer

    def addLayer(self, layer):
        registry = QgsProject.instance()
        if not registry.mapLayer(layer.id()):
            registry.addMapLayer(layer)
        else:
            node=QgsProject.instance().layerTreeRoot().findLayer(layer.id())
            if node is not None:
                node.setItemVisibilityChecked(True)
            layer.triggerRepaint()
            self._iface.mapCanvas().refresh()

    def setContourProperties( self, layer, properties ):
        for key in list(properties.keys()):
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
            'Method',
            'ApplyColors',
            'ColorRamp',
            'ReverseRamp'
            ]:
            properties[key] = str(layer.customProperty('ContourPlugin.'+key))
        if not properties['ContourId']:
            return None
        return properties

    def contourLayers(self, wanted={}):
        for layer in list(QgsProject.instance().mapLayers().values()):
            properties = self.getContourProperties(layer)
            if not properties:
                continue
            ok = True
            for key in list(wanted.keys()):
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
            return self.getContourProperties(list(layerSet.values())[0]).get('ContourId')
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

    def makeContourLayer(self,ctype):
        self._generator.setContourType(ctype)
        extend=self.uExtend.itemData(self.uExtend.currentIndex())
        self._generator.setContourExtendOption(extend)
        name = self.uOutputName.text()
        fields=self._generator.fields()
        geomtype=self._generator.wkbtype()
        crs=self._generator.crs()
        vl = self.createVectorLayer(geomtype, name, ctype,fields,crs)
        levels=[]
        vl.startEditing()
        for feature in self._generator.contourFeatures():
            vl.addFeature( feature )
            levels.append((feature['index'],feature['label']))
        vl.updateExtents()
        vl.commitChanges()
        rendtype='line' if ctype == ContourType.line else 'polygon'
        self.applyRenderer(vl,rendtype,levels)
        self.addLayer(vl)
        self.adviseUser(tr("Contour layer {0} created").format(vl.name()))

    def dataChanged( self ):
        x,y,z=self._generator.data()
        if z is not None:
            zmin=np.min(z)
            zmax=np.max(z)
            ndp=self.uPrecision.value()
            if zmax-zmin > 0:
                ndp2=ndp
                while 10**(-ndp2) > (zmax-zmin)/100 and ndp2 < 10:
                    ndp2 += 1
                if ndp2 != ndp:
                    self.uPrecision.setValue(ndp2)
                    self.adviseUser(tr("Resetting the label precision to match range of data values"))
            if not self.uSetMinimum.isChecked():
                self.uMinContour.setValue(zmin)
            if not self.uSetMaximum.isChecked():
                self.uMaxContour.setValue(zmax)
            gridded=self._generator.isGridded()
            self.uUseGrid.setEnabled(gridded)
            self.uUseGrid.setChecked(gridded)
            self.uUseGridLabel.setEnabled(gridded)
            description='Contouring {0} points'.format(len(z))
            if gridded:
                gridshape=self._generator.gridShape()
                description=description+' in a {0} x {1} grid'.format(*gridshape)
            else:
                description=description+' (not in regular grid)'
            self.uLayerDescription.setText(description)
        else:
            self.uLayerDescription.setText(tr("No data selected for contouring"))

    def setLabelFormat( self ):
        ndp=self.uPrecision.value()
        trim=self.uTrimZeroes.isChecked()
        units=self.uLabelUnits.text()
        self._generator.setLabelFormat(ndp,trim,units)

    def formatLevel( self, level ):
        return self._generator.formatLevel(level)

    def applyRenderer( self, layer, type, levels ):
        if not self.uApplyColors.isChecked():
            return
        ramp=self.uColorRamp.colorRamp()
        reversed=self.uReverseRamp.isChecked()
        if ramp is None:
            return
        nLevels=len(levels)
        if nLevels < 2:
            return
        renderer=QgsCategorizedSymbolRenderer('index')
        for i, level in enumerate(levels):
            value,label=level
            rampvalue=float(i)/(nLevels-1)
            if reversed:
                rampvalue=1.0-rampvalue
            color=ramp.color(rampvalue)
            symbol=None
            if type=='line':
                symbol=QgsLineSymbol.createSimple({})
            else:
                symbol=QgsFillSymbol.createSimple({'outline_style':'no'})
            symbol.setColor(color)
            category=QgsRendererCategory(value,symbol,label)
            renderer.addCategory(category)
        layer.setRenderer(renderer)

    def colorRampToString( self, ramp ):
        if ramp is None:
            return '';
        d=QDomDocument()
        d.appendChild(QgsSymbolLayerUtils.saveColorRamp('ramp',ramp,d))
        rampdef=d.toString()
        return rampdef

    def stringToColorRamp( self, rampdef ):
        try:
            if '<' not in rampdef:
                return None
            d=QDomDocument()
            d.setContent(rampdef)
            return QgsSymbolLayerUtils.loadColorRamp( d.documentElement() )
        except:
            return None

    def saveSettings( self ):
        settings=QSettings()
        base='/plugins/contour/'
        mode=(LAYERS if self.uLayerContours.isChecked() else
              BOTH if self.uBoth.isChecked() else
              FILLED if self.uFilledContours.isChecked() else
              LINES)
        list=self.uLevelsList
        values=' '.join([list.item(i).text() for i in range(0, list.count())])
        settings.setValue(base+'mode',mode)
        settings.setValue(base+'levels',str(self.uNContour.value()))
        settings.setValue(base+'values',values)
        settings.setValue(base+'interval',str(self.uContourInterval.value()))
        settings.setValue(base+'extend',self.uExtend.itemData(self.uExtend.currentIndex()))
        settings.setValue(base+'method',self.uMethod.itemData(self.uMethod.currentIndex()))
        settings.setValue(base+'precision',str(self.uPrecision.value()))
        settings.setValue(base+'setmin','yes' if self.uSetMinimum.isChecked() else 'no')
        settings.setValue(base+'minval',str(self.uMinContour.value()))
        settings.setValue(base+'setmax','yes' if self.uSetMaximum.isChecked() else 'no')
        settings.setValue(base+'maxval',str(self.uMaxContour.value()))
        settings.setValue(base+'trimZeroes','yes' if self.uTrimZeroes.isChecked() else 'no')
        settings.setValue(base+'units',self.uLabelUnits.text())
        settings.setValue(base+'applyColors','yes' if self.uApplyColors.isChecked() else 'no')
        settings.setValue(base+'ramp',self.colorRampToString(self.uColorRamp.colorRamp()))
        settings.setValue(base+'reverseRamp','yes' if self.uReverseRamp.isChecked() else 'no')

    def loadSettings( self ):
        settings=QSettings()
        base='/plugins/contour/'
        try:
            mode=settings.value(base+'mode')
            if mode==LAYERS:
                self.uLayerContours.setChecked(True)
            elif mode==BOTH:
                self.uBoth.setChecked(True)
            elif mode==FILLED:
                self.uFilledContours.setChecked(True)
            else:
                self.uLinesContours.setChecked(True)

            levels=settings.value(base+'levels')
            if levels is not None and levels.isdigit():
                self.uNContour.setValue(int(levels))

            values=settings.value(base+'values')
            if values is not None:
                self.uLevelsList.clear()
                for value in values.split():
                    self.uLevelsList.addItem(value)

            setmin=settings.value(base+'setmin') == 'yes'
            self.uSetMinimum.setChecked(setmin)
            if setmin:
                try:
                    value=settings.value(base+'minval')
                    self.uMinContour.setValue(float(value))
                except:
                    pass

            setmax=settings.value(base+'setmax') == 'yes'
            self.uSetMaximum.setChecked(setmax)
            if setmax:
                try:
                    value=settings.value(base+'maxval')
                    self.uMaxContour.setValue(float(value))
                except:
                    pass

            extend=settings.value(base+'extend')
            index = self.uExtend.findData(extend)
            if index >= 0:
                self.uExtend.setCurrentIndex(index)

            method=settings.value(base+'method')
            index = self.uMethod.findData(method)
            if index >= 0:
                self.uMethod.setCurrentIndex(index)

            precision=settings.value(base+'precision')
            if precision is not None and precision.isdigit():
                ndp=int(precision)
                self.uPrecision.setValue(ndp)
                self.uMinContour.setDecimals( ndp )
                self.uMaxContour.setDecimals( ndp )

            units=settings.value(base+'units')
            if units is not None:
                self.uLabelUnits.setText(units)

            applyColors=settings.value(base+'applyColors')
            self.uApplyColors.setChecked(applyColors=='yes')

            ramp=settings.value(base+'ramp')
            ramp=self.stringToColorRamp(ramp)
            if ramp:
                self.uColorRamp.setColorRamp(ramp)

            reverseRamp=settings.value(base+'reverseRamp')
            self.uReverseRamp.setChecked(reverseRamp=='yes')

            trimZeroes=settings.value(base+'trimZeroes')
            self.uTrimZeroes.setChecked(trimZeroes=='yes')
        except:
            pass
