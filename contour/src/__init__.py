#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#       __init__.py
#
#       Copyright 2010 Lionel Roubeyrie <lionel.roubeyrie@gmail.com>
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

'''Modifications :
0.9.2 : Fix an import bug if Matplotlib is in RC version
0.9.1 : Fixes the memory layer bug where vl.updateFieldMap() needs to be called
        for updating the attributes list + *contours levels must be
        converted to float (C. Crook).
        Make distinction for old contours functions from MPL<1.0.0 and the new
        tricontours ones (raise warnings on irregular grid with old MPL version)
0.9.0 : Use the new matplotlib triangulation facility (version > 1.0.0 required)
        now can handle any point layer without griddind required, the ability to
        reopen previously contoured layers with all options reloaded, and a new
        option to fix extend levels.
0.8.0 : Fixed CRS handling. Disabled Ok button once calculation is done.
        Added properties to layer to allow recalculation
0.7.3 : bug correction on quantile computation
0.7.2 : Adding field "label" to resulting layers with a precision parameter,
        quantile level computation method, resulting layers name modification
0.7.1 : Minor change for checking dependencies with the PPI
0.7 : Add more acceptable datatypes (integer, float, ...) from PostgreSQL
0.6 : Pass contour.py Qt4 compliant and remove Qt3 signals handling






'''


def name():
    return "Contour plugin"

def icon():
    return "./contour.png"

def description():
    return "Trace contour lines (isolines) and filled contours from a points grid"

def version():
    return "0.9.2"

def qgisMinimumVersion():
    return "1.5"

def author():
    return "Lionel Roubeyrie"

def email():
    return "lionel.roubeyrie@gmail.com"

def classFactory(iface):
    from contour import Contour
    return Contour(iface)
