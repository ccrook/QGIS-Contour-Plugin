#!/usr/bin/python3

import sys
import numpy as np
sys.path.append('..')
from ContourMethod import calculateLevels

tests=[
    ('equal',{'ncontour':5}),
    ('equal',{'ncontour':5,'min':10}),
    ('equal',{'ncontour':5,'max':20}),
    ('equal',{'ncontour':5,'min':10,'max':20}),
    ('quantile',{'ncontour':5}),
    ('quantile',{'ncontour':5,'min':10}),
    ('quantile',{'ncontour':5,'max':20}),
    ('quantile',{'ncontour':5,'min':10,'max':20}),
    ('log',{'ncontour':5 }),
    ('log',{'ncontour':5,'min':0.01}),
    ('log',{'ncontour':5,'max':20}),
    ('log',{'ncontour':5,'min':0.01,'max':20}),
    ('log',{'ncontour':5,'max':20,'mantissa':'1 3'}),
    ('interval',{'interval':2.5}),
    ('interval',{'interval':2.5,'min':10}),
    ('interval',{'interval':2.5,'max':20}),
    ('manual',{'levels':'0.0 1.0 2.0 3.0 7.0 11.0 99.0'}),
    ('manual',{'levels':[0.0,1.0,2.0,3.0,7.0,11.0,99.0]}),
]

np.random.seed(42)
zdata=np.random.rand(30)*35.0
np.random.shuffle(zdata)
print("Testdata: [",", ".join(("{0:.2f}".format(z) for z in zdata)))

for ntest,test in enumerate(tests):
    try:
        method,params=test
        print("\nTest {0}".format(ntest));
        strprm="/ ".join(("{0}: {1}".format(k,params[k]) for k in sorted(params.keys()))) 
        print("   {0}: {1}".format(method,strprm))
        levels=calculateLevels(zdata,method,**params)
        print("   {0}".format(", ".join(("{0:.3f}".format(l) for l in levels))))
    except RuntimeError as e:
        print("   Exception: {0}".format(e.args[0]))
    
