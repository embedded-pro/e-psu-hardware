"""KiCad 10 pcbnew import with the SWIG iterator fix (its proxy calls it.next(), which Python 3 SWIG lacks)."""
import pcbnew

if not hasattr(pcbnew.SwigPyIterator, "next"):
    pcbnew.SwigPyIterator.next = lambda self: self.__next__()
