import numpy as np
import random

class DataGridder:
    '''
    Examine a list of x,y coordinates to see if they lie on a grid, and 
    calculate the grid order and shape if they do
    '''

    def __init__( self, x=None, y=None ):
        self.setData(x,y)

    def setData(self,x,y):
        '''
        Set the x,y values to be tested

        '''
        self._x=None if x is None else x.astype(np.float64)
        self._y=None if y is None else y.astype(np.float64)
        self._tested=False
        self._isValid=None
        self._gridOrder=None
        self._gridShape=None

    def calcGrid(self):
        '''
        Calculate the grid for the current x,y values.
        Returns gridshape, gridorder
        gridshape is the shape (nrow,ncol) of the grid
        index is the index for reordering if required, otherwise None

        If the points do not lie on a grid returns gridshape as None

        The grid x and y values are calculated as 
            xg=x[gridorder].reshape(gridshape)
            xg=y[gridorder].reshape(gridshape)
        if gridorder is not None, else simply reshaping x and y
        '''
        if self._x is None or self._y is None:
            return None, None
        if not self._tested:
            self._tested=True
            if len(self._x) > 4:
                try:
                    self._tryGridOrdered()
                    valid=self._gridIsValid()
                    if not valid:
                        self._tryGridReorder()
                        valid=self._gridIsValid()
                    if not valid:
                        self._gridShape=None
                        self._gridOrder=None
                    self._isValid=valid
                except:
                    pass
        return self._gridShape,self._gridOrder

    def _tryGridOrdered( self ):
        '''
        Test if the data as ordered form a regular grid
        '''
        # Simple test assumes grid is ordered, so dot product of vector from
        # first node to second with difference from n to n+1 should be positive
        # except when n to n+1 jumps back to start of a new row.  So negative 
        # dot products should identify start of rows, and be equally spaced in
        # data set.
        x=self._x
        y=self._y
        l = len(x)
        xd=np.diff(x)
        yd=np.diff(y)
        ld = l-1
        dotprod=xd[0:ld-1]*xd[1:ld]+yd[0:ld-1]*yd[1:ld]
        ends = np.flatnonzero(dotprod<0)+2
        if len(ends)<2:
            return False
        nr = ends[0]
        nc = len(ends) // 2+1
        if (nr >= 2) and (nc >= 2) and (nr*nc == l) and (all(ends%nr <= 1)):
           self._gridShape=(nc,nr)
           self._gridOrder=None
           return True
        return False

    def _tryGridReorder( self ):
        '''
        Test for grid by reordering rows and columns
        '''
        # More complex test.  Attempts to identify grid rows by identifying
        # start and end of an outside edge.  Does this by finding the point 
        # furthest from the centre, then the point furthest from it (assumed 
        # to be across the diagonal, and finally the point furthest from the
        # line between them, assumed to be the opposite end of an edge.  Then 
        # uses the vector direction of the edge to sort the points into rows
        # and columns.  Finally checks that all the resultant grid cells are
        # valid, meaning not re-entrant.
        
        x=self._x
        y=self._y
        xm=np.mean(x)
        ym=np.mean(y)
        i0=np.argmax(np.square(x-xm)+np.square(y-ym))
        x0=x[i0]
        y0=y[i0]
        u = x-x0
        v = y-y0
        i3=np.argmax(u*u+v*v)
        du1=u[i3]
        dv1=v[i3]
        offset=u*dv1-v*du1
        i1=np.argmax(offset)
        i2=np.argmin(offset)
        scl = np.sqrt(du1*du1+dv1*dv1)
        u /= scl
        v /= scl
        # Transform to set the corners i0,i1,i2,i3
        # to (-1,-1),(-1,1),(1,-1),(1,1).  Note that 
        # uv(i0) = (0,0)
        m=np.array([
            [1.0,0,0,0],
            [1.0,u[i1],v[i1],u[i1]*v[i1]],
            [1.0,u[i2],v[i2],u[i2]*v[i2]],
            [1.0,u[i3],v[i3],u[i3]*v[i3]],
            ])
        coefs=np.linalg.solve(m,np.array([[-1,-1],[1,-1],[-1,1],[1,1]]))
        prms=np.vstack((np.ones(u.shape),u,v,u*v))
        uv=prms.T.dot(coefs)
        u=uv[:,0]
        v=uv[:,1]
        # Now guess at a spacing that will separate the 
        # first row from the second...
        vrow=1+np.min(v[v+1 > np.abs(u+1)])
        npt=u.shape[0]
        # Count the elements in the first row
        ncol=v[v < (vrow/2-1)].shape[0]
        nrow=int(npt/ncol)
        # Test that row count is a divisor of the
        # number of elements
        if nrow*ncol != npt:
            return False
        # Add values to each u for each row (based on sorting of v)
        # so that u values will sort into elements across each row
        # in turn.
        uwid=(np.max(u)-np.min(u))*2.0
        iu=np.argsort(v)
        urow=np.floor_divide(np.arange(npt),ncol)*uwid
        t=np.vstack((u[iu],v[iu],urow)).T
        urow1=u
        urow1[iu] += urow
        # Now have ig, which is the sort order for converting into a
        # grid
        self._gridOrder=np.argsort(urow1)
        self._gridShape=(nrow,ncol)
        return True

    def _gridIsValid( self ):
        if not self._gridShape:
            return False
        u=self._x.copy() if self._gridOrder is None else self._x[self._gridOrder]
        v=self._y.copy() if self._gridOrder is None else self._y[self._gridOrder]
        u=u.reshape(self._gridShape)
        v=v.reshape(self._gridShape)
        dudu=u[1:,:]-u[:-1,:]
        dvdu=v[1:,:]-v[:-1,:]
        dudv=u[:,1:]-u[:,:-1]
        dvdv=v[:,1:]-v[:,:-1]

        # Test the cross product at each of the internal angles in turn
        # They should all have the same sign...

        dotprod=dudu[:,:-1]*dvdv[:-1,:]-dvdu[:,:-1]*dudv[:-1,:]
        imax=np.argmax(np.abs(dotprod))
        sign = 1.0 if dotprod.flat[imax] > 0 else -1.0
        dotprod *= sign
        if np.any(dotprod < 0):
            return False
        dotprod=sign*(dudu[:,1:]*dvdv[:-1,:]-dvdu[:,1:]*dudv[:-1,:])
        if np.any(dotprod < 0):
            return False
        dotprod=sign*(dudu[:,1:]*dvdv[1:,:]-dvdu[:,1:]*dudv[1:,:])
        if np.any(dotprod < 0):
            return False
        dotprod=sign*(dudu[:,:-1]*dvdv[1:,:]-dvdu[:,:-1]*dudv[1:,:])
        if np.any(dotprod < 0):
           return False
        return True

