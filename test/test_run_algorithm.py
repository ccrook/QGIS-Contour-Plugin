import processing
layer=iface.mapCanvas().currentLayer()
r=processing.run(
   "contourplugin:generatecontours",
      { 'ContourInterval' : 1, 
        'ContourLevels' : '', 
        'ContourMethod' : 1, 
        'ContourType' : 0, 
        'ExtendOption' : 0, 
        'InputField' : '"z"', 
        'InputLayer' : layer,
        'LabelTrimZeros' : False, 
        'LabelUnits' : '', 
        'MaxContourValue' : None, 
        'MinContourValue' : None, 
        'NContour' : 20, 
        'OutputLayer' : 'memory:' }
        )
layer=r['OutputLayer']
QgsProject.instance().addMapLayer(layer)