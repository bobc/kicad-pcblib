#!/usr/bin/env python
#!/usr/bin/env python3

# freepcb2pretty

# Written in 2014-2015 by Chris Pavlina
# CC0 1.0 Universal

# This script reads a FreePCB library file and converts it to a KiCad
# "pretty" library, primarily for generating the KiCad IPC libraries.

# Tested on Python 2.7, 3.2

# ROUNDED PADS EXCEPTIONS LIST:
# This file specifies exceptions to pad-rounding; use --rounded-pad-exceptions.
# This is one regex per line, compatible with the Python 're' library, that
# will be matched to the component name.
# Caveats:
#  - Regular expression will be matched at the beginning of the name, not
#    found inside it
#  - Regular expressions are matched before stripping L/M/N
# Blank lines are ignored.

# ROUNDED CENTER PADS EXCEPTIONS LIST:
# This file worls just like the rounded pads exceptions list, except only
# applies to pads located at the center of a part. This allows rounding all
# pads except a thermal pad.

# 3D MAP:
# This file is used to specify 3D models for use with each module. The format
# is a sequence of "key: value" pairs, one per line, like this:
# mod: MODULE-NAME
# 3dmod: 3D-MODEL-NAME
# rotx: rotate X (floating degrees)
# roty: rotate Y
# rotz: rotate Z
# scax: scale X (floating millimeters)
# scay:
# scaz:
# offx: offset X (floating millimeters)
# offy: offset Y
# offz: offset Z
#
# Comments are not allowed, but blank lines are. All except mod/3dmod are
# optional (default is scale 1/1/1, rot 0/0/0, off 0/0/0.

import io
import datetime
import time
import sys
import re
import os.path

try:
    unicode
except NameError:
    unicode = str

VERSION="1.0"

TEXT_SIZE = 1.
TEXT_THICK = 0.2

VERBOSE = 1

PAD_CIRCLE = 1
PAD_SQUARE = 2
PAD_RECT = 3
PAD_RRECT = 4
PAD_OVAL = 5
PAD_OCT = 6

class SexpSymbol (object):
    """An s-expression symbol. This is a bare text object which is exported
    without quotation or escaping. Be careful to use valid text here..."""

    def __init__ (self, s):
        self.s = s

    def __str__ (self):
        return self.s

    def __repr__ (self):
        return "SexpSymbol(%r)" % self.s

    def value (self):
        return self.s;

# For short code
S = SexpSymbol

def SexpDump (sexp, f, indentlevel=0):
    """Dump an s-expression to a file.
    indentlevel is used for recursion.
    """

    if isinstance (sexp, list):
        f.write ("(")
        first = True
        for i in sexp:
            if first:
                first = False
            else:
                f.write (" ")

            SexpDump (i, f, indentlevel + 1)
        f.write (")")

        if indentlevel == 1 :
            f.write("\n")

    elif isinstance (sexp, (str, unicode)):
        f.write ('"')
        f.write (sexp.encode ("unicode_escape").decode ("ascii"))
        f.write ('"')

    else:
        f.write (str(sexp))

def indent_string (s):
    """Put two spaces before each line in s"""
    lines = s.split ("\n")
    lines = ["  " + i for i in lines]
    lines = [("" if i == "  " else i) for i in lines]
    return "\n".join (lines)

def parse_string (s):
    """Grab a string, stripping it of quotes; return string, length."""
    if s[0] != '"':
        string, delim, garbage = s.partition (" ")
        return string.strip (), len (string) + 1

    else:
        try:
            second_quote = s[1:].index ('"') + 1
        except ValueError:
            return s[1:], len (s)
        else:
            beyond = s[second_quote + 1:]
            beyond_stripped = beyond.lstrip ()
            extra_garbage = len (beyond) - len (beyond_stripped)
            return s[1:second_quote], second_quote + 1 + extra_garbage

def to_mm (n, units = "NM"):
    """Convert FreePCB units to floating millimeters"""

    if units == "NM":
        return float(n) / 1000000.
    elif units == "MM":
        return float(n)
    elif units == "MIL":
        return float(n) * 0.0254

    return 

def from_mm (n):
    return float(n) * 1000000.


class Library (object):
    def __init__ (self, file_in=None, opts=None):
        self.Modules = []
        if file_in is None and opts is None:
            self.opts = None
        elif file_in is not None and opts is not None:
            self.opts = opts

            file_in.get_string (allow_blank=False)
            while not file_in.at_end ():
                self.Modules.append (PCBmodule (file_in, opts))
        else:
            raise TypeError ("Expected one or three arguments")

    def __str__ (self):
        return "\n".join (str (i) for i in self.Modules) + "\n"

    def __iadd__ (self, other):
        """Add the contents of another library into this."""
        for i in self.Modules:
            for j in other.Modules:
                if i.Name == j.Name:
                    raise Exception ("Duplicate module name \"%s\"" % i.Name)
        self.Modules.extend (other.Modules)
        self.opts = other.opts # In case it was blank
        return self

    def strip_lmn (self):
        """Strip least/most/nominal specifier from all modules"""
        for i in self.Modules:
            i.strip_lmn ()

class PCBmodule (object):
    def __init__ (self, file_in, opts):
        """Read out the footprint from the FreePCB module."""
        
        self.opts = opts

        # 3D data - to be edited externally
        self.ThreeDName = None
        self.ThreeDScale = [1.0, 1.0, 1.0]
        self.ThreeDOffset = [0.0, 0.0, 0.0]
        self.ThreeDRot = [0.0, 0.0, 0.0]


        # Pre-indent data
        self.Name = ""
        self.Author = ""
        self.Source = ""
        self.Description = ""

        # key, value = file_in.get_string (allow_blank=False)

        while not file_in.key == "units" and not file_in.at_end ():
            if file_in.key == "name":
                self.Name = file_in.value
            elif file_in.key == "author":
                self.Author = file_in.value
            elif file_in.key == "source":
                self.Source = file_in.value
            elif file_in.key == "description":
                self.Description = file_in.value
            else:
                raise Exception ("Unexpected key \"%s\" on line %d."
                        % (file_in.key, file_in.Lineno - 1))
            file_in.get_string (allow_blank=False)
                
        assert self.Name
        #assert self.Author
        #assert self.Source
        #assert self.Description

        # Post-indent data
        self.Units = None
        self.SelectionRect = None
        self.RefText = None
        self.ValText = ""
        self.Centroid = "0 0 0 0"
        self.Graphics = []

        self.UserText = []

        while not file_in.key == "name" and not file_in.at_end ():
            #key = file_in.peek_key ()
            if file_in.key == "units":
                self.Units = file_in.value
                file_in.get_string (allow_blank=False)
            elif file_in.key == "sel_rect":
                self.SelectionRect = file_in.value
                file_in.get_string (allow_blank=False)
            elif file_in.key == "ref_text":
                self.RefText = file_in.value
                file_in.get_string (allow_blank=False)
            elif file_in.key == "value_text":
                self.ValText = file_in.value
                file_in.get_string (allow_blank=False)
            elif file_in.key == "text":
                # TODO self.ValText = file_in.value
                self.UserText.append (file_in.value)
                file_in.get_string (allow_blank=False)
            elif file_in.key == "centroid":
                self.Centroid = file_in.value
                file_in.get_string (allow_blank=False)
            elif file_in.key == "adhesive":
                # ignored
                file_in.get_string (allow_blank=False)
            elif file_in.key == "outline_polyline":
                self.Graphics.append (Polyline.create_from_freepcb (file_in, opts, self.Units))
            elif file_in.key == "n_pins":
                file_in.get_string (allow_blank=True) # Skip the n_pins line
            elif file_in.key == "pin":
                self.Graphics.append (Pin.create_from_freepcb (self.Name, file_in, opts, self.Units))
            else:
                raise Exception ("Unexpected key \"%s\" on line %d."
                        % (file_in.key, file_in.Lineno - 1))

        # Don't actually need this info, but check for it anyway just to
        # ensure the file format hasn't changed.
        #assert self.Units == "NM"

        assert self.SelectionRect
        assert self.RefText
        # TODO
        # assert self.Centroid == "0 0 0 0"

        self.tedit = time.time()


    def __str__ (self):
        s = "PCB footprint:\n" \
                + "  Name: " + self.Name + "\n" \
                + "  Author: " + self.Author + "\n" \
                + "  Source: " + self.Source + "\n" \
                + "  Description: " + self.Description + "\n"
        if self.ThreeDname is not None: \
                s += "  3D model: " + self.ThreeDName + "\n"
        for i in self.Graphics:
            s += indent_string (str (i))
        return s

    def kicad_sexp (self):
        sexp = [S('module')]

        sexp.append (self.Name)
        sexp.append ([S("layer"), "F.Cu"])
        sexp.append ([S("tedit"), "%08X" % int (self.tedit)])

        sexp.append ([S("descr"), str(self.Description)])

        # todo:
        # sexp.append ([S("attr"), S("smd")])

        sexp.append ([S("fp_text"),
            S("reference"), "REF**",
            [S("at"), 0, 0],
            [S("layer"), "F.SilkS"],
            [S("effects"),
                [S("font"),
                    [S("size"), 0.8, 0.8],
                    [S("thickness"), 0.15]]]])

        sexp.append ([S("fp_text"),
            S("value"), self.Name,
            [S("at"), 0, 0],
            [S("layer"), "F.Fab"],
            [S("effects"),
                [S("font"),
                    [S("size"), 0.5, 0.5],
                    [S("thickness"), 0.1]]]])

        for t in self.UserText:
            name, length = parse_string (t)
            params = t[length:]
            params = [i for i in params.split()]

            swidth = to_mm(params[0], self.Units) *len(name)
            px = to_mm(params[1], self.Units) + swidth/2
            py = -to_mm(params[2], self.Units) - to_mm(params[0], self.Units)/2

            sexp.append ([S("fp_text"),
                S("user"), name,
                [S("at"), px, py ],
                [S("layer"), "F.SilkS"],
                [S("effects"),
                    [S("font"),
                        [S("size"), to_mm(params[0], self.Units), to_mm(params[0], self.Units)],
                        [S("thickness"), to_mm(params[4], self.Units)]]
                    
                    ]
                ])

        # Polylines
        for i in self.Graphics:
            if not isinstance (i, Polyline): continue
            sexp.extend (i.kicad_sexp ())

        # Pads/pins
        for i in self.Graphics:
            if not isinstance (i, Pin): continue
            sexp.extend (i.kicad_sexp ())

        # 3D
        if self.ThreeDName is not None:
            sexp.append ([S("model"), self.ThreeDName,
                [S("at"), [S("xyz")] + self.ThreeDOffset],
                [S("scale"), [S("xyz")] + self.ThreeDScale],
                [S("rotate"), [S("xyz")] + self.ThreeDRot]])

        return sexp

    def strip_lmn (self):
        """Strip least/most/nominal specifier from all modules"""
        if self.Name[-1] in "LMNlmn":
            self.Name = self.Name[:-1]

    def bounding_box (self):
        """Return a (left, right, top, bottom) bounding box"""
        sub_boxes = [i.bounding_box() for i in self.Graphics]
        lefts = [i[0] for i in sub_boxes]
        rights = [i[1] for i in sub_boxes]
        tops = [i[2] for i in sub_boxes]
        bottoms = [i[3] for i in sub_boxes]
        
        bb = [min(lefts), max(rights), max(tops), min(bottoms)]
        return bb

    def add_courtyard (self, spacing):
        left, right, top, bottom = self.bounding_box ()
        left -= from_mm (spacing)
        right += from_mm (spacing)
        top += from_mm (spacing)
        bottom -= from_mm (spacing)

        cy = Polyline ()
        cy.Points = [(left, top), (right, top), (right, bottom), (left, bottom),
                (left, top)]
        cy.KicadLinewidth = 0.05
        cy.Layer = "F.CrtYd"

        self.Graphics.append (cy)

class Polyline (object):
    def __init__ (self):
        """Read a polyline object."""

        self.opts = None
        self.Points = []
        self.Linewidth = None
        self.Closed = False
        self.Layer = "F.SilkS"
        self.KicadLinewidth = 0.15
        self.Units = "NM"

    @classmethod
    def create_from_freepcb (cls, file_in, opts, units):
        self = cls ()
        self.opts = opts
        self.Units = units

        # First point and line width
        #key, value = file_in.get_string (allow_blank=False)
        assert file_in.key == "outline_polyline"
        value = file_in.value
        try:
            value = [float(i) for i in value.split ()]
        except ValueError:
            raise Exception ("Line %d must contain a list of three values."
                % (file_in.Lineno - 1))
        if len (value) != 3:
            raise Exception ("Line %d must contain a list of three values."
                % (file_in.Lineno - 1))

        self.Linewidth = 0.15#value[0]
        #print value[0]
        self.Points.append (value[1:]) 

        # Subsequent points
        key, value = file_in.get_string (allow_blank=False)

        while key == "next_corner":
            assert key == "next_corner"
            try:
                value = [float(i) for i in value.split ()]
            except ValueError:
                raise Exception ("Line %d must contain a list of three values."
                    % (file_in.Lineno - 1))
            if len (value) != 3:
                raise Exception ("Line %d must contain a list of three values."
                    % (file_in.Lineno - 1))
            self.Points.append (value[:2])
            # Third number is "side style", which KiCad doesn't have.

            key, value = file_in.get_string (allow_blank=False)

        if key == "close_polyline":
            file_in.get_string (allow_blank=False)
            self.Closed = True
            self.Points.append (self.Points[0])
        return self

    def __str__ (self):
        s = "Polyline:\n" \
                + "  Line width: " + str (self.Linewidth) + "\n"
        for i in self.Points:
            s += "  Point: %d, %d\n" % tuple (i)
        return s

    def kicad_sexp (self):

        sexp = []
        last_corner = self.Points[0]
        for i in self.Points[1:]:
            sexp.append ([S("fp_line"),
                [S("start"), to_mm (last_corner[0], self.Units), to_mm (-last_corner[1], self.Units)],
                [S("end"), to_mm (i[0], self.Units), to_mm (-i[1], self.Units)],
                [S("layer"), self.Layer],
                [S("width"), self.KicadLinewidth]])
            last_corner = i

        return sexp

    def bounding_box (self):
        """Return a (left, right, top, bottom) bounding box"""
        left = min (i[0] for i in self.Points)
        right = max (i[0] for i in self.Points)
        top = max (i[1] for i in self.Points)
        bottom = min (i[1] for i in self.Points)
        return (left, right, top, bottom) 

class Pin (object):
    def __init__ (self, modname):
        """Read a pin object."""


        self.opts = None
        self.ModName = modname
        self.Name = None
        self.DrillDiam = None
        self.Coords = []
        self.Angle = None

        self.TopPad = None
        self.InnerPad = None
        self.BottomPad = None

        self.Units = "NM"

    @classmethod
    def create_from_freepcb (cls, modname, file_in, opts, units):
        self = cls (modname)

        self.opts = opts
        self.Units = units

        #key, value = file_in.get_string (allow_blank=False)
        assert file_in.key == "pin"

        self.Name, length = parse_string (file_in.value)
        value = file_in.value[length:]
        try:
            value = [float(i) for i in value.split ()]
        except ValueError:
            raise Exception ("Line %d must contain a list of four values."
                    % (file_in.Lineno - 1))
        if len (value) != 4:
            raise Exception ("Line %d must contain a list of four values."
                    % (file_in.Lineno - 1))

        self.DrillDiam = value[0]
        self.Coords = value[1:3]
        self.Angle = value[3]

        file_in.get_string (allow_blank=False)

        while file_in.key.endswith ("_pad"):
            
            if file_in.key == "top_pad":
                self.TopPad = Pad (file_in.value, file_in)
            elif file_in.key == "inner_pad":
                self.InnerPad = Pad (file_in.value, file_in)
            elif file_in.key == "bottom_pad":
                self.BottomPad = Pad (file_in.value, file_in)
            else:
                raise Exception ("Unexpected key \"%s\" on line %d."
                        % (file_in.key, file_in.Lineno - 1))

            file_in.get_string (allow_blank=False)
        
        return self

    def __str__ (self):
        s = "Pin:\n" + \
                "  Name      : " + self.Name + "\n" + \
                "  Drill diam: " + str (self.DrillDiam) + "\n" + \
                "  Angle     : " + str (self.Angle) + "\n" + \
                "  Coords    : %d, %d\n" % tuple(self.Coords) + \
                "  TopPad    : " + str (self.TopPad) + "\n" + \
                "  InnerPad  : " + str (self.InnerPad) + "\n" + \
                "  BottomPad : " + str (self.BottomPad) + "\n"
        return s

    def kicad_sexp (self):
        """See Library.kicad_repr"""

        if VERBOSE:
            print (self)

        if self.DrillDiam == 0:
            # Surface mount

            if self.TopPad:
                sx, sy = self.TopPad.Width, self.TopPad.Len1 + self.TopPad.Len2
            else:
                sx, sy = self.BottomPad.Width, self.BottomPad.Len1 + self.BottomPad.Len2

            if self.Angle == 90 or self.Angle == 270:
                sx, sy = sy, sx

            # Rounded pads
            can_round_pads = True
            for regex in self.opts.rpexceptions:
                if regex.match (self.ModName):
                    can_round_pads = False
            can_round_center = True
            for regex in self.opts.rcexceptions:
                if regex.match (self.ModName):
                    can_round_center = False

            if self.opts.roundedpads is None:
                shape = "rect"
            elif not can_round_center and (0, 0) == tuple (self.Coords):
                shape = "rect"
            elif self.opts.roundedpads == "all":
                shape = "oval" if can_round_pads else "rect"
            elif self.opts.roundedpads == "allbut1":
                if can_round_pads:
                    shape = "rect" if self.Name == "1" else "oval"
                else:
                    shape = "rect"
            else:
                assert False

            # Output shape
            sexp = [ [S("pad"), self.Name, S("smd"), S(shape),
                        [S("at"), to_mm (self.Coords[0], self.Units), -to_mm (self.Coords[1], self.Units)],
                        [S("size"), to_mm (sy, self.Units), to_mm (sx, self.Units)],
                        [S("layers"), "F.Cu", "F.Paste", "F.Mask"] ] ]

        else:
            # PTH
            sx, sy = self.TopPad.Width, self.TopPad.Len1 + self.TopPad.Len2

            if self.TopPad.Shape == PAD_CIRCLE or self.TopPad.Shape == PAD_SQUARE or self.TopPad.Shape == PAD_OCT:
                sy = sx

            if self.Angle == 90 or self.Angle == 270:
                sx, sy = sy, sx
            else:
                if sy == 0:
                    sy = sx

            #if self.Name == "1":
            #    shape = "rect"
            #else:
            #    
            if self.TopPad.Shape == PAD_CIRCLE or self.TopPad.Shape == PAD_OCT:
                shape = "circle"
            elif self.TopPad.Shape == PAD_SQUARE or self.TopPad.Shape == PAD_RECT:
                shape = "rect"
            elif self.TopPad.Shape == PAD_OVAL:
                shape = "oval"
            else:
                shape = "circle"

            sexp = [[S("pad"), self.Name, S("thru_hole"), S(shape),
                [S("at"), to_mm (self.Coords[0], self.Units), -to_mm (self.Coords[1], self.Units)],
                [S("size"), to_mm (sx, self.Units), to_mm (sy, self.Units)],
                [S("drill"), to_mm (self.DrillDiam, self.Units)],
                [S("layers"), "*.Cu", "*.Mask"]]]

        if VERBOSE:
            print (SexpDump (sexp, sys.stdout))

        return sexp

    def bounding_box (self):
        """Return a (left, right, top, bottom) bounding box"""
        sx, sy = self.TopPad.Width, self.TopPad.Len1 + self.TopPad.Len2
        if self.Angle == 90:
            sx, sy = sy, sx
        else:
            assert self.Angle == 0

        left = self.Coords[0] - (sy / 2)
        right = self.Coords[0] + (sy / 2)
        top = self.Coords[1] + (sx / 2)
        bottom = self.Coords[1] - (sx / 2)

        return (left, right, top, bottom)

class Pad (object):
    def __init__ (self, value, file_in):
        try:
            value = [float(i) for i in value.split ()]
        except ValueError:
            raise Exception ("Line %d must contain a list of four or five values."
                    % (file_in.Lineno - 1))

        if len (value) < 4:
            raise Exception ("Line %d must contain a list of at least four values."
                    % (file_in.Lineno - 1))

        #if len (value) > 5:
        #    print ("Warning: Line %d contains > 5 values." % (file_in.Lineno - 1))

        if len (value) == 4:
            # default corner radius
            value.append(0)

        self.Shape, self.Width, self.Len1, self.Len2, self.CornRad = value[:5]

    def __str__ (self):
        return "Pad: shape %d, (w %d, L1 %d, L2 %d), corner %d" % \
                (self.Shape, self.Width, self.Len1, self.Len2, self.CornRad)

class FreePCBfile (object):
    """This just wraps a FreePCB text file, reading it out in pieces."""

    def __init__ (self, f):
        self.File = [i.rstrip () for i in f.readlines ()]
        self.File.reverse ()
        self.Lineno = 1

        self.key = ""
        self.value = ""

    def get_string (self, allow_blank):
        # Retrieve a line of the format "key: value"

        while self.File and not self.File[-1].strip ():
            self.File.pop ()
            self.Lineno += 1

        if len (self.File):
            assert len (self.File)
            # Gobble blank lines
            self.Lineno += 1

            self.key, delim, self.value = self.File.pop ().partition (":")
            self.key = self.key.strip ()
            self.value = self.value.strip ()
            if self.value.startswith ('"') and self.value.endswith ('"'):
                self.value, throwaway = parse_string (self.value)
            if not self.value:
                raise Exception ("Line %d: expected value" % (self.Lineno - 1))
        else:
            self.key = "eof"
            self.value = ""

        return self.key, self.value

    def indent_level (self):
        # Get the current indentation level based on the current line, two
        # spaces = tab.
        line = self.File[-1]
        i = 0
        halfindents = 0
        while i < len (line):
            if line[i] == '\t':
                halfindents += 2
            elif line[i] == ' ':
                halfindents += 1
            else:
                break
            i += 1
        return halfindents // 2
    
    def at_end (self):
        while self.File and not self.File[-1].strip ():
            self.File.pop ()
            self.Lineno += 1

        return not self.File

    def peek_key (self):
        # Read the key from the current line without popping it
        assert len (self.File)
        key, delim, value = self.File[-1].partition (":")
        return key.strip ()

def process_3dmap (mapfile, library):
    """Read all 3D mappings from mapfile, applying them to library."""

    f = open (mapfile)
    ff = FreePCBfile (f) # Exploit the format to reuse a parser
    current_module = None
    while not ff.at_end ():
        key, value = ff.get_string (allow_blank=False)
        if key == "mod":
            for i in library.Modules:
                if i.Name == value:
                    current_module = i
                    break
            else:
                raise Exception (("3D map (line %d): couldn't find " +
                    "module \"%s\"") % (ff.Lineno - 1, value))
        elif key == "3dmod":
            if current_module is None:
                raise Exception (("3D map (line %d): cannot specify " +
                    "parameters before module name") % (ff.Lineno - 1))
            current_module.ThreeDName = value
        elif key.startswith ("rot"):
            if current_module is None:
                raise Exception (("3D map (line %d): cannot specify " +
                    "parameters before module name") % (ff.Lineno - 1))
            index = ord (key[3]) - ord('x')
            current_module.ThreeDRot[index] = float (value)
        elif key.startswith ("sca"):
            if current_module is None:
                raise Exception (("3D map (line %d): cannot specify " +
                    "parameters before module name") % (ff.Lineno - 1))
            index = ord (key[3]) - ord('x')
            current_module.ThreeDScale[index] = float (value)
        elif key.startswith ("off"):
            if current_module is None:
                raise Exception (("3D map (line %d): cannot specify " +
                    "parameters before module name") % (ff.Lineno - 1))
            index = ord (key[3]) - ord('x')
            current_module.ThreeDOffset[index] = float (value)
        else:
            raise Exception ("3D map (line %d): unknown key \"%s\"" %
                    (ff.Lineno - 1, key))

def main (args=None, zipfile=None):
    """
    When called from other Python code, 'zipfile' is accepted in lieu of a list
    of files; the files will be pulled from the zipfile object.
    """

    from argparse import ArgumentParser
    description = "Read a FreePCB library file and convert it to Kicad " + \
            "format, with output to the specified directory. Uses the new " + \
            "millimeter format. If multiple files are given, they will be " + \
            "merged."
    p = ArgumentParser (description=description)
    p.add_argument ("-v", "--version", action="version",
            version="%(prog)s " + VERSION)

    p.add_argument ("outdir", metavar="DIR", type=str,
            help="Output directory")
    p.add_argument ("infile", metavar="FILE", type=str, nargs='*',
        help="FreePCB-format input(s)")
    blurbp = p.add_mutually_exclusive_group ()
    blurbp.add_argument ("--blurb", dest="blurb", action="store_const",
            const=True, default=False,
            help="Include a blurb about freepcb2pretty in the output file's" +
            " comments (default: no)")
    blurbp.add_argument ("--no-blurb", dest="blurb", action="store_const",
            const=False, default=False)
    p.add_argument ("--3dmap", dest="threedmap", type=str,
            help="File mapping PCB modules to 3D models. See source code " + \
                    "(comments in header) for documentation.")
    roundp = p.add_mutually_exclusive_group ()
    roundp.add_argument ("--rounded-pads", dest="roundedpads",
            action="store_const", const="all", default=None,
            help="Round all corners of square pads")
    roundp.add_argument ("--rounded-except-1", dest="roundedpads",
            action="store_const", const="allbut1", default=None,
            help="Round all corners of square pads, except pad 1")
    p.add_argument ("--rounded-pad-exceptions", dest="rpexcept", type=str,
            help="Exceptions list for rounded pads. See source code " + \
                    "(comments in header) for documentation.")
    p.add_argument ("--rounded-center-exceptions", dest="rcexcept", type=str,
            help="Exceptions list for rounded center pads. See source code " + \
                    "(comments in header) for documentation.")
    p.add_argument ("--strip-lmn", dest="strip_lmn", action="store_const",
            const=True, default=False,
            help="Strip final L/M/N specifiers from names")
    p.add_argument ("--add-courtyard", dest="courtyard", type=float,
            default=None,
            help="Add a courtyard a fixed number of mm outside the bounding box")
    p.add_argument ("--hash-time", dest="hashtime", action="store_const",
            const=True, default=False,
            help="Set a fake edit time on the footprints using a hash")
    args = p.parse_args (args)

    # Parse rounded pads exceptions file?
    rpexceptions = []
    if args.rpexcept is not None:
        with open (args.rpexcept) as f:
            for line in f:
                line = line.strip ()
                if not line:
                    continue
                rpexceptions.append (re.compile (line))
    # It's really an argument, so put it inside args
    args.rpexceptions = rpexceptions

    # Parse rounded center pads exceptions file?
    rcexceptions = []
    if args.rcexcept is not None:
        with open (args.rcexcept) as f:
            for line in f:
                line = line.strip ()
                if not line:
                    continue
                rcexceptions.append (re.compile (line))
    # It's really an argument, so put it inside args
    args.rcexceptions = rcexceptions

    # Main conversion
    print ("Loading FreePCB library...")
    library = Library ()
    for filename in args.infile:
        print (filename)
        f = open (filename)
        ff = FreePCBfile (f)
        sublibrary = Library (ff, args)
        library += sublibrary
        f.close ()
    if zipfile is not None:
        for filename in zipfile.namelist ():
            f = zipfile.open (filename, 'r')
            f_wrapped = io.TextIOWrapper (f, 'utf8')
            ff = FreePCBfile (f_wrapped)
            sublibrary = Library (ff, args)
            library += sublibrary
            f.close ()

    # Strip L/M/N?
    if args.strip_lmn:
        library.strip_lmn ()

    # Add 3D models
    if args.threedmap is not None:
        process_3dmap (args.threedmap, library)

    # Add courtyards
    if args.courtyard is not None:
        for i in library.Modules:
            i.add_courtyard (args.courtyard)

    # Fake timestamps?
    if args.hashtime:
        import hashlib
        import struct
        for i in library.Modules:
            i.tedit = 0
            md5 = hashlib.md5()
            md5.update(str(i.kicad_sexp()).encode('utf8'))
            md5sum = md5.digest()
            i.tedit = struct.unpack("<L", md5sum[0:4])[0]

    print ("Generating KiCad library...")
    for i in library.Modules:
        path = os.path.join (args.outdir, i.Name + '.kicad_mod')
        print (path)
        # sanitise the name
        path = path.replace ("/", "_")
        with open (path, 'w') as f:
            sexp = i.kicad_sexp ()
            SexpDump (sexp, f)
            # sexpdata.dump (i.kicad_sexp (), f)

if __name__ == "__main__":
    main ()
