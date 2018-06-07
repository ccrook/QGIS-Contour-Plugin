import numpy as np
import math
import inspect
from collections import namedtuple

# Need to use QObject.tr on method name, description

class ContourMethodError( RuntimeError ):
    pass

ContourMethod=namedtuple('ContourMethod','code name calc required optional description')

methods=[]

tr=lambda x: x

def _numberListParam( param, list ):
    if isinstance(list,str):
        list=list.split()
    values=[]
    v0=None
    for v in list:
        try:
            v=float(v)
        except ValueError:
            raise ContourMethodError(tr('Invalid value {0} in {1}').format(vs,param))
        if v0 is not None and v <= v0:
            raise ContourMethodError(tr('Values not increasing in {0}').format(param))
        values.append(v)
        v0=v
    return np.array(values)

def _paramValue( pt, param, value ):
    try:
        value=pt(value)
    except:
        raise ContourMethodError(tr('Invalid value for contour {0} parameter: {1}')
                    .format(param,value))
    return value

_floatParam=lambda p,v: _paramValue(float,p,v)
_intParam=lambda p,v: _paramValue(int,p,v)

_paramtypes={
    'min': _floatParam,
    'max': _floatParam,
    'ncontour': _intParam,
    'maxcontour': _intParam,
    'interval': _floatParam,
    'offset': _floatParam,
    'levels': _numberListParam,
    'mantissa': _numberListParam,
    }

def _evalParam(p,v):
    if p not in _paramtypes:
        raise ContourMethodError(tr('Invalid contour method parameter {0}').format(p))
    return _paramtypes[p](p,v)

def _methodFunc(z,f,name,req,opt,kwa):
    pav=[]
    kwv={}
    for k in req:
        if k not in kwa:
            raise ContourMethodError(tr('Parameter {0} missing in {1}').format(k,name))
        pav.append(_evalParam(k,kwa[k]))
    for k in opt:
        v=kwa.get(k)
        if v is not None:
            kwv[k]=_evalParam(k,v)
    return f(z,*pav,**kwv)

def contourmethod(code=None,name=None,description=None):
    def mf2( f ):
        nonlocal code, name, description
        if code is None: 
            code=f.__name__
        if name is None:
            name=code
        if description is None:
            description=f.__doc__
        sig=inspect.signature(f)
        req=[]
        opt=[]
        for pn in sig.parameters:
            p=sig.parameters[pn]
            if p.kind == inspect.Parameter.POSITIONAL_ONLY:
                req.append(pn)
            else:
                opt.append(pn)
        func=lambda z,**kwa: _methodFunc(z,f,name,req,opt,kwa)
        methods.append(ContourMethod(code,name,func,req,opt,description))
        return func
    return mf2


def _range( z, min, max ):
    zmin = min if min is not None else np.min(z)
    zmax = max if max is not None else np.max(z)
    return zmin, zmax

@contourmethod('equal','N equal intervals')
def calcEqualContours( z, ncontour, min=None, max=None ):
    'Equally spaced contours between min and max'
    zmin,zmax=_range(z,min,max)
    if zmax <= zmin:
        raise ContourMethodError(tr('Invalid contour range - zmin=zmax'))
    if ncontour < 1:
        raise ContourMethodError(tr('Invalid number of contours - must be greater than 0'))
    return np.linspace(zmin,zmax,ncontour+1)

@contourmethod('quantile','N quantiles')
def calcQuantileContours( z, ncontour, min=None, max=None ):
    'Contours at percentiles of data distribution between min and max'
    if min is not None:
        z=z[z >= min]
    if max is not None:
        z=z[z <= max]
    if len(z) < 2:
        raise ContourMethodError(tr('Not enough z values to calculate quantiles'))
    if ncontour < 1:
        raise ContourMethodError(tr('Invalid number of contours - must be greater than 0'))
    pcnt=np.linspace(0.0,100.0,ncontour+1)
    return np.percentile(z,pcnt)
    

@contourmethod('log','logarithmic intervals')
def calcLogContours( z, ncontour, min=None, max=None, mantissa=[1,2,5] ):
    'Contours at up to n values 1, 2, 5 * 10^n between min and max'
    zmin,zmax=_range(z,min,max)
    if ncontour < 1:
        raise ContourMethodError(tr('Invalid number of contours - must be greater than 0'))
    for m in mantissa:
        if m < 1.0 or m >= 10.0:
            raise ContourMethodError(tr('Log contour mantissa must be between 1 and 10'))
    if zmax <= 0:
        raise ContourMethodError(tr('Cannot make log spaced contours on negative or 0 data'))
    if zmin <= 0:
        zmin=zmax/(10**(math.ceil(float(ncontour)/len(mantissa))))
    exp0=int(math.floor(math.log10(zmin)))
    exp1=int(math.ceil(math.log10(zmax)))
    levels=[m*10**e for e in range(exp0,exp1+1) for m in mantissa]
    for i,v in enumerate(levels):
        if v > zmin:
            break
    if i > 1:
        levels=levels[i-1:]
    levels.reverse()
    for i,v in enumerate(levels):
        if v < zmax:
            break
    if i > 1:
        levels=levels[i-1:]
    levels.reverse()
    if len(levels) > ncontour:
        if min is not None and max is None:
            levels=levels[:ncontour]
        else:
            levels=levels[-ncontour:]
    return levels

@contourmethod('interval','Fixed contour interval')
def calcIntervalContours( z, interval, offset=0.0,min=None, max=None, maxcontours=50):
    'Contours at specified spacing between min and max'
    if interval <= 0:
        raise ContourMethodError(tr("Contour interval must be greater than zero"))
    zmin,zmax=_range(z,min,max)
    zmin -= offset
    zmax -= offset
    nmin=np.floor(zmin/interval)
    nmax=np.ceil(zmax/interval)
    if nmax == nmin:
        nmax += 1
    nmax += 1
    if nmax-nmin >= maxcontours:
        raise ContourMethodError(tr("Number of contours ({0}) exceeds maximum allowed ({1})")
                           .format(nmax-nmin,self.MaxContours))
    return np.arange(nmin,nmax)*interval+offset

@contourmethod('manual','Specified contour levels')
def parseContours( z, levels ):
    'Contours at specified levels'
    return levels


def calculateLevels( z, method, **params ):
    method=method.lower()
    for m in methods:
        if m.code==method:
            return m.calc(z,**params)
    raise ContourMethodError("Invalid contouring method {0}".format(method))
