# Tiny helper function to build Delauney triangulation in consisten
# python environment and avoid qhull crash in QGIS
import sys
import numpy as np
from matplotlib.tri import Triangulation

if len(sys.argv) != 3:
    sys.exit(1)

xy=np.load(sys.argv[1])
trig=Triangulation(xy[0],xy[1])
np.save(sys.argv[2],trig.triangles)

