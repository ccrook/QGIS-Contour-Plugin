
import sys
sys.path.append('../contour')
import DataGridder
import numpy as np

test=('''
 10 40 0
 20 40 0
 30 40 0
 40 40 0
 50 40 0
 50 30 0
 40 30 10
 30 30 -10
 20 30 10
 10 30 0
 10 20 0
 20 20 0
 30 20 0
 40 20 0
 50 20 0
          ''')

x=[]
y=[]
z=[]
for l in test.split('\n'):
    p=l.split()
    if len(p)==3:
        x.append(float(p[0]))
        y.append(float(p[1]))
        z.append(float(p[2]))
x=np.array(x)
y=np.array(y)

import pdb; pdb.set_trace()
g=DataGridder.DataGridder(x,y)
print(g.calcGrid())
