# -*- coding: utf-8 -*-

# Form implementation generated from reading ui file 'frmContour.ui'
#
# Created by: PyQt5 UI code generator 5.5.1
#
# WARNING! All changes made in this file will be lost!

from PyQt5 import QtCore, QtGui, QtWidgets

class Ui_ContourDialog(object):
    def setupUi(self, ContourDialog):
        ContourDialog.setObjectName("ContourDialog")
        ContourDialog.setWindowModality(QtCore.Qt.NonModal)
        ContourDialog.resize(478, 653)
        ContourDialog.setSizeGripEnabled(True)
        self.gridLayout_3 = QtWidgets.QGridLayout(ContourDialog)
        self.gridLayout_3.setObjectName("gridLayout_3")
        self.groupBox_2 = QtWidgets.QGroupBox(ContourDialog)
        self.groupBox_2.setObjectName("groupBox_2")
        self.gridLayout = QtWidgets.QGridLayout(self.groupBox_2)
        self.gridLayout.setObjectName("gridLayout")
        self.formLayout_2 = QtWidgets.QFormLayout()
        self.formLayout_2.setContentsMargins(-1, 0, -1, -1)
        self.formLayout_2.setObjectName("formLayout_2")
        self.label_3 = QtWidgets.QLabel(self.groupBox_2)
        self.label_3.setObjectName("label_3")
        self.formLayout_2.setWidget(0, QtWidgets.QFormLayout.LabelRole, self.label_3)
        self.uLayerName = QtWidgets.QComboBox(self.groupBox_2)
        sizePolicy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        sizePolicy.setHorizontalStretch(0)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.uLayerName.sizePolicy().hasHeightForWidth())
        self.uLayerName.setSizePolicy(sizePolicy)
        self.uLayerName.setStatusTip("")
        self.uLayerName.setObjectName("uLayerName")
        self.formLayout_2.setWidget(0, QtWidgets.QFormLayout.FieldRole, self.uLayerName)
        self.label_4 = QtWidgets.QLabel(self.groupBox_2)
        self.label_4.setObjectName("label_4")
        self.formLayout_2.setWidget(1, QtWidgets.QFormLayout.LabelRole, self.label_4)
        self.uDataField = gui.QgsFieldExpressionWidget(self.groupBox_2)
