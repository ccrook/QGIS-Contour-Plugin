import numpy as np

"""
ContourUtils provide support functions for the contouring tool
"""


def _discardIndex(x, y, x0, y0, resolution, index):
    values, ix = np.unique(
        ((x[index] - x0) / resolution).astype(int), return_inverse=True
    )
    values, iy = np.unique(
        ((y[index] - y0) / resolution).astype(int), return_inverse=True
    )
    mix = ix * values.shape[0] + iy
    values, indices = np.unique(mix, return_inverse=True)
    thinned = np.zeros(values.shape, dtype=int)
    thinned[indices] = index
    return thinned


def discardDuplicatePoints(x, y, resolution, isLonLat=False):
    """
    Crude routine to remove duplicate points.  Somewhat randomly
    discards points that are no longer required.  Returns indices
    of points to use.

    Resolution is the resolution within which points are merged

    If isLonLat is true then x,y are assumed to be longitude/latitudes
    and are very approximately converted to metres for the test.
    """
    if isLonLat:
        meanlon = np.mean(x)
        meanlat = np.mean(y)
        y = (y - meanlat) * 100000.0
        x = (x - meanlon) * 100000.0 * np.cos(np.radians(meanlat))

    x0 = np.min(x)
    y0 = np.min(y)
    index = np.arange(x.shape[0], dtype=int)
    if resolution <= 0:
        return index
    index = _discardIndex(x, y, x0, y0, resolution, index)
    index = _discardIndex(x, y, x0 + resolution / 2, y0, resolution, index)
    index = _discardIndex(x, y, x0, y0 + resolution / 2, resolution, index)
    index = _discardIndex(
        x, y, x0 + resolution / 2, y0 + resolution / 2, resolution, index
    )
    return index


def calcDefaultNdp(levels):
    try:
        levels = np.array(levels)
        ldiff = levels[1:] - levels[:-1]
        ldmin = np.min(ldiff[ldiff > 0.0])
        # Allow 2dp on minimum increment
        ldmin /= 100
        ndp = 0
        while ndp < 10 and ldmin < 1.0:
            ndp += 1
            ldmin *= 10.0
        while ndp > 0:
            factor = 10 ** (ndp - 1)
            rerr = np.abs(levels * factor - np.round(levels * factor))
            diff = np.max(rerr)
            if diff >= 0.05:
                break
            ndp -= 1
    except:
        ndp = 4  # Arbitrary!
    return ndp
