"""
PC-BASIC - values.py
Types, values and conversions

(c) 2013, 2014, 2015, 2016 Rob Hagemans
This file is released under the GNU GPL version 3 or later.
"""

import string
import functools
import math

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

from . import fp
from . import error
from . import util
from . import basictoken as tk


# BASIC type sigils:
# Integer (%) - stored as two's complement, little-endian
# Single (!) - stored as 4-byte Microsoft Binary Format
# Double (#) - stored as 8-byte Microsoft Binary Format
# String ($) - stored as 1-byte length plus 2-byte pointer to string space
INT = '%'
SNG = '!'
DBL = '#'
STR = '$'

# storage size in bytes
TYPE_TO_SIZE = {STR: 3, INT: 2, SNG: 4, DBL: 8}
SIZE_TO_TYPE = {2: INT, 3: STR, 4: SNG, 8: DBL}


def null(sigil):
    """Return null value for the given type."""
    return (sigil, bytearray(TYPE_TO_SIZE[sigil]))

def size_bytes(name):
    """Return the size of a value type, by variable name or type char."""
    return TYPE_TO_SIZE[name[-1]]


###############################################################################
# type checks

def pass_string(inp, err=error.TYPE_MISMATCH):
    """Check if variable is String-valued."""
    if inp[0] != '$':
        raise error.RunError(err)
    return inp

def pass_number(inp, err=error.TYPE_MISMATCH):
    """Check if variable is numeric."""
    if inp[0] not in ('%', '!', '#'):
        raise error.RunError(err)
    return inp


###############################################################################
# convert between BASIC String and token address bytes

def string_length(in_string):
    """Get string length as Python int."""
    return in_string[1][0]

def string_address(in_string):
    """Get string address as Python int."""
    return integer_to_int(Values.from_bytes(in_string[1][1:]), unsigned=True)


###############################################################################
# convert between BASIC Integer and Python int


def int_to_integer(n, unsigned=False):
    """Convert Python int to BASIC Integer."""
    maxint = 0xffff if unsigned else 0x7fff
    if n > maxint or n < -0x8000:
        raise error.RunError(error.OVERFLOW)
    if n < 0:
        n = 0x10000 + n
    return ('%', bytearray((n&0xff, n >> 8)))

def integer_to_int(in_integer, unsigned=False):
    """Convert BASIC Integer to Python int."""
    s = in_integer[1]
    if unsigned:
        return 0x100 * s[1] + s[0]
    else:
        # 2's complement signed int, least significant byte first,
        # sign bit is most significant bit
        value = 0x100 * (s[1] & 0x7f) + s[0]
        if (s[1] & 0x80) == 0x80:
            return -0x8000 + value
        else:
            return value


###############################################################################
# error handling

def float_safe(fn):
    """Decorator to handle floating point errors."""
    def wrapped_fn(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except (ValueError, ArithmeticError) as e:
            return self._math_error_handler.handle(e)
    return wrapped_fn


class MathErrorHandler(object):
    """Handles floating point errors."""

    # types of errors that do not always interrupt execution
    soft_types = (error.OVERFLOW, error.DIVISION_BY_ZERO)

    def __init__(self, screen):
        """Setup handler."""
        self._screen = screen
        self._do_raise = False

    def pause_handling(self, do_raise):
        """Pause local handling of floating point errors."""
        self._do_raise = do_raise

    def handle(self, e):
        """Handle Overflow or Division by Zero."""
        if isinstance(e, ValueError):
            # math domain errors such as SQR(-1)
            math_error = error.IFC
        elif isinstance(e, OverflowError):
            math_error = error.OVERFLOW
        elif isinstance(e, ZeroDivisionError):
            math_error = error.DIVISION_BY_ZERO
        else:
            raise e
        if (self._do_raise or self._screen is None or
                math_error not in self.soft_types):
            # also raises exception in error_handle_mode!
            # in that case, prints a normal error message
            raise error.RunError(math_error)
        else:
            # write a message & continue as normal
            self._screen.write_line(error.RunError(math_error).message)
        # return max value for the appropriate float type
        if e.args and e.args[0] and isinstance(e.args[0], fp.Float):
            return fp.pack(e.args[0])
        return fp.pack(fp.Single.max.copy())


###############################################################################

class Values(object):
    """Handles BASIC strings and numbers."""

    def __init__(self, screen, string_space, double_math):
        """Setup values."""
        self._math_error_handler = MathErrorHandler(screen)
        self._strings = string_space
        # double-precision EXP, SIN, COS, TAN, ATN, LOG
        self._double_math = double_math

    ###########################################################################
    # convert between BASIC and Python values

    @float_safe
    def to_value(self, basic_val):
        """Convert BASIC value to Python value."""
        typechar = basic_val[0]
        if typechar == '$':
            return self._strings.copy(basic_val)
        elif typechar == '%':
            return integer_to_int(basic_val)
        elif typechar in ('#', '!'):
            return fp.unpack(basic_val).to_value()

    @float_safe
    def from_value(self, python_val, typechar):
        """Convert Python value to BASIC value."""
        if typechar == '$':
            return self._strings.store(python_val)
        elif typechar == '%':
            return int_to_integer(python_val)
        elif typechar == '!':
            return fp.pack(fp.Single.from_value(python_val))
        elif typechar == '#':
            return fp.pack(fp.Double.from_value(python_val))

    def to_int(self, inp, unsigned=False):
        """Round numeric variable and convert to Python integer."""
        return integer_to_int(self.to_integer(inp, unsigned))

    def from_bool(self, boo):
        """Convert Python boolean to Integer."""
        return self.from_bytes('\xff\xff') if boo else self.from_bytes('\0\0')

    def to_bool(self, basic_value):
        """Convert Integer to Python boolean."""
        return not self.is_zero(basic_value)

    ###########################################################################
    # convert to and from internal representation

    @staticmethod
    def to_bytes(basic_val):
        """Convert BASIC value to internal byte representation."""
        return bytearray(basic_val[1])

    @staticmethod
    def from_bytes(token_bytes):
        """Convert internal byte representation to BASIC value."""
        return (SIZE_TO_TYPE[len(token_bytes)], bytearray(token_bytes))

    ###########################################################################
    # type conversions

    def to_integer(self, inp, unsigned=False):
        """Check if variable is numeric, convert to Int."""
        assert isinstance(inp, tuple)
        maxint = 0xffff if unsigned else 0x7fff
        typechar = inp[0]
        if typechar == '%':
            return inp
        elif typechar in ('!', '#'):
            val = fp.unpack(inp).round_to_int()
            if val > maxint or val < -0x8000:
                # overflow
                raise error.RunError(error.OVERFLOW)
            return int_to_integer(val, unsigned=True)
        else:
            # type mismatch
            raise error.RunError(error.TYPE_MISMATCH)

    @float_safe
    def to_single(self, num):
        """Check if variable is numeric, convert to Single."""
        assert isinstance(num, tuple)
        typechar = num[0]
        if typechar == '!':
            return num
        elif typechar == '%':
            return fp.pack(fp.Single.from_int(integer_to_int(num)))
        elif typechar == '#':
            return fp.pack(fp.unpack(num).round_to_single())
        else:
            raise error.RunError(error.TYPE_MISMATCH)

    @float_safe
    def to_double(self, num):
        """Check if variable is numeric, convert to Double."""
        assert isinstance(num, tuple)
        typechar = num[0]
        if typechar == '#':
            return num
        elif typechar == '%':
            return fp.pack(fp.Double.from_int(integer_to_int(num)))
        elif typechar == '!':
            return ('#', bytearray(4) + num[1])
        else:
            raise error.RunError(error.TYPE_MISMATCH)

    def to_float(self, num, allow_double=True):
        """Check if variable is numeric, convert to Double or Single."""
        if num and num[0] == '#' and allow_double:
            return num
        else:
            return self.to_single(num)

    def to_most_precise(self, left, right):
        """Check if variables are numeric and convert to highest-precision."""
        left_type, right_type = left[0][-1], right[0][-1]
        if left_type == '#' or right_type == '#':
            return (self.to_double(left), self.to_double(right))
        elif left_type == '!' or right_type == '!':
            return (self.to_single(left), self.to_single(right))
        elif left_type == '%' or right_type == '%':
            return (self.to_integer(left), self.to_integer(right))
        else:
            raise error.RunError(error.TYPE_MISMATCH)

    def to_type(self, typechar, value):
        """Check if variable can be converted to the given type and convert."""
        if typechar == '$':
            return pass_string(value)
        elif typechar == '%':
            return self.to_integer(value)
        elif typechar == '!':
            return self.to_single(value)
        elif typechar == '#':
            return self.to_double(value)

    ###############################################################################

    def round(self, x):
        """Round to nearest whole number."""
        return fp.pack(fp.unpack(self.to_float(x)).iround())

    def is_zero(self, x):
        """Return whether a number is zero."""
        x = pass_number(x)
        typechar = x[0]
        if typechar == '%':
            return integer_to_int(x) == 0
        else:
            return fp.unpack(x).is_zero()

    ###############################################################################
    # math functions

    @float_safe
    def _call_float_function(self, fn, *args):
        """Convert to IEEE 754, apply function, convert back."""
        args = [self.to_float(arg, self._double_math) for arg in args]
        floatcls = fp.unpack(args[0]).__class__
        try:
            args = (fp.unpack(arg).to_value() for arg in args)
            return fp.pack(floatcls().from_value(fn(*args)))
        except ArithmeticError as e:
            # positive infinity
            raise e.__class__(floatcls.max.copy())

    def sqr(self, x):
        """Square root."""
        return self._call_float_function(math.sqrt, x)

    def exp(self, x):
        """Exponential."""
        return self._call_float_function(math.exp, x)

    def sin(self, x):
        """Sine."""
        return self._call_float_function(math.sin, x)

    def cos(self, x):
        """Cosine."""
        return self._call_float_function(math.cos, x)

    def tan(self, x):
        """Tangent."""
        return self._call_float_function(math.tan, x)

    def atn(self, x):
        """Inverse tangent."""
        return self._call_float_function(math.atan, x)

    def log(self, x):
        """Logarithm."""
        return self._call_float_function(math.log, x)

    ###########################################################################

    def sgn(self, x):
        """Sign."""
        x = pass_number(x)
        if x[0] == '%':
            inp_int = integer_to_int(x)
            return int_to_integer(0 if inp_int == 0 else (1 if inp_int > 0 else -1))
        else:
            return int_to_integer(fp.unpack(x).sign())

    def floor(self, x):
        """Truncate towards negative infinity (INT)."""
        x = pass_number(x)
        return x if x[0] == '%' else fp.pack(fp.unpack(x).ifloor())

    def fix(self, x):
        """Truncate towards zero."""
        inp = pass_number(x)
        if inp[0] == '%':
            return inp
        elif inp[0] == '!':
            # needs to be a float to avoid overflow
            return fp.pack(fp.Single.from_int(fp.unpack(inp).trunc_to_int()))
        elif inp[0] == '#':
            return fp.pack(fp.Double.from_int(fp.unpack(inp).trunc_to_int()))


    ###############################################################################
    # numeric operators

    @float_safe
    def add(self, left, right):
        """Add two numbers."""
        left, right = self.to_most_precise(left, right)
        if left[0] in ('#', '!'):
            return fp.pack(fp.unpack(left).iadd(fp.unpack(right)))
        else:
            # return Single to avoid wrapping on integer overflow
            return fp.pack(fp.Single.from_int(
                                integer_to_int(left) + integer_to_int(right)))

    @float_safe
    def subtract(self, left, right):
        """Subtract two numbers."""
        return self.add(left, self.negate(right))

    def abs(self, inp):
        """Return the absolute value of a number. No-op for strings."""
        if inp[0] == '%':
            val = abs(integer_to_int(inp))
            if val == 32768:
                return fp.pack(fp.Single.from_int(val))
            else:
                return int_to_integer(val)
        elif inp[0] in ('!', '#'):
            out = (inp[0], inp[1][:])
            out[1][-2] &= 0x7F
            return out
        return inp

    def negate(self, inp):
        """Negation (unary -). No-op for strings."""
        if inp[0] == '%':
            val = -integer_to_int(inp)
            if val == 32768:
                return fp.pack(fp.Single.from_int(val))
            else:
                return int_to_integer(val)
        elif inp[0] in ('!', '#'):
            out = (inp[0], inp[1][:])
            out[1][-2] ^= 0x80
            return out
        return inp

    @float_safe
    def power(self, left, right):
        """Left^right."""
        if (left[0] == '#' or right[0] == '#') and self._double_math:
            return self._call_float_function(lambda a, b: a**b, self.to_double(left), self.to_double(right))
        else:
            if right[0] == '%':
                return fp.pack(fp.unpack(self.to_single(left)).ipow_int(integer_to_int(right)))
            else:
                return self._call_float_function(lambda a, b: a**b, self.to_single(left), self.to_single(right))

    @float_safe
    def multiply(self, left, right):
        """Left*right."""
        if left[0] == '#' or right[0] == '#':
            return fp.pack( fp.unpack(self.to_double(left)).imul(fp.unpack(self.to_double(right))) )
        else:
            return fp.pack( fp.unpack(self.to_single(left)).imul(fp.unpack(self.to_single(right))) )

    @float_safe
    def divide(self, left, right):
        """Left/right."""
        if left[0] == '#' or right[0] == '#':
            return fp.pack( fp.div(fp.unpack(self.to_double(left)), fp.unpack(self.to_double(right))) )
        else:
            return fp.pack( fp.div(fp.unpack(self.to_single(left)), fp.unpack(self.to_single(right))) )

    @float_safe
    def divide_int(self, left, right):
        """Left\\right."""
        dividend = self.to_int(left)
        divisor = self.to_int(right)
        if divisor == 0:
            # division by zero, return single-precision maximum
            raise ZeroDivisionError(fp.Single(dividend<0, fp.Single.max.man, fp.Single.max.exp))
        if (dividend >= 0) == (divisor >= 0):
            return int_to_integer(dividend / divisor)
        else:
            return int_to_integer(-(abs(dividend) / abs(divisor)))

    @float_safe
    def mod(self, left, right):
        """Left modulo right."""
        divisor = self.to_int(right)
        dividend = self.to_int(left)
        if divisor == 0:
            # division by zero, return single-precision maximum
            raise ZeroDivisionError(fp.Single(dividend<0, fp.Single.max.man, fp.Single.max.exp))
        mod = dividend % divisor
        if dividend < 0 or mod < 0:
            mod -= divisor
        return int_to_integer(mod)

    def bitwise_not(self, right):
        """Bitwise NOT, -x-1."""
        return int_to_integer(-self.to_int(right)-1)

    def bitwise_and(self, left, right):
        """Bitwise AND."""
        return int_to_integer(
            integer_to_int(self.to_integer(left), unsigned=True) &
            integer_to_int(self.to_integer(right), unsigned=True), unsigned=True)

    def bitwise_or(self, left, right):
        """Bitwise OR."""
        return int_to_integer(
            integer_to_int(self.to_integer(left), unsigned=True) |
            integer_to_int(self.to_integer(right), unsigned=True), unsigned=True)

    def bitwise_xor(self, left, right):
        """Bitwise XOR."""
        return int_to_integer(
            integer_to_int(self.to_integer(left), unsigned=True) ^
            integer_to_int(self.to_integer(right), unsigned=True), unsigned=True)

    def bitwise_eqv(self, left, right):
        """Bitwise equivalence."""
        return int_to_integer(0xffff-(
            integer_to_int(self.to_integer(left), unsigned=True) ^
            integer_to_int(self.to_integer(right), unsigned=True)), unsigned=True)

    def bitwise_imp(self, left, right):
        """Bitwise implication."""
        return int_to_integer(
            (0xffff - integer_to_int(self.to_integer(left), unsigned=True)) |
            integer_to_int(self.to_integer(right), unsigned=True), unsigned=True)


    ###############################################################################
    # string operations

    def concat(self, left, right):
        """Concatenate strings."""
        return self._strings.store(
            self._strings.copy(pass_string(left)) +
            self._strings.copy(pass_string(right)))


    ###############################################################################
    # number and string operations

    def _bool_eq(self, left, right):
        """Return true if left == right, false otherwise."""
        if left[0] == '$':
            return (self._strings.copy(pass_string(left)) ==
                    self._strings.copy(pass_string(right)))
        else:
            left, right = self.to_most_precise(left, right)
            if left[0] in ('#', '!'):
                return fp.unpack(left).equals(fp.unpack(right))
            else:
                return integer_to_int(left) == integer_to_int(right)

    def bool_gt(self, left, right):
        """Ordering: return -1 if left > right, 0 otherwise."""
        if left[0] == '$':
            left = self._strings.copy(pass_string(left))
            right = self._strings.copy(pass_string(right))
            shortest = min(len(left), len(right))
            for i in range(shortest):
                if left[i] > right[i]:
                    return True
                elif left[i] < right[i]:
                    return False
            # the same so far...
            # the shorter string is said to be less than the longer,
            # provided they are the same up till the length of the shorter.
            if len(left) > len(right):
                return True
            # left is shorter, or equal strings
            return False
        else:
            left, right = self.to_most_precise(left, right)
            if left[0] in ('#', '!'):
                return fp.unpack(left).gt(fp.unpack(right))
            else:
                return integer_to_int(left) > integer_to_int(right)

    def equals(self, left, right):
        """Return -1 if left == right, 0 otherwise."""
        return self.from_bool(self._bool_eq(left, right))

    def not_equals(self, left, right):
        """Return -1 if left != right, 0 otherwise."""
        return self.from_bool(not self._bool_eq(left, right))

    def gt(self, left, right):
        """Ordering: return -1 if left > right, 0 otherwise."""
        return self.from_bool(self.bool_gt(left, right))

    def gte(self, left, right):
        """Ordering: return -1 if left >= right, 0 otherwise."""
        return self.from_bool(not self.bool_gt(right, left))

    def lte(self, left, right):
        """Ordering: return -1 if left <= right, 0 otherwise."""
        return self.from_bool(not self.bool_gt(left, right))

    def lt(self, left, right):
        """Ordering: return -1 if left < right, 0 otherwise."""
        return self.from_bool(self.bool_gt(right, left))

    def plus(self, left, right):
        """Binary + operator: add or concatenate."""
        if left[0] == '$':
            return self.concat(left, right)
        else:
            return self.add(left, right)

    ##########################################################################
    # conversion

    def cvi(self, x):
        """CVI: return the int value of a byte representation."""
        cstr = self._strings.copy(pass_string(x))
        error.throw_if(len(cstr) < 2)
        return self.from_bytes(cstr[:2])

    def cvs(self, x):
        """CVS: return the single-precision value of a byte representation."""
        cstr = self._strings.copy(pass_string(x))
        error.throw_if(len(cstr) < 4)
        return self.from_bytes(cstr[:4])

    def cvd(self, x):
        """CVD: return the double-precision value of a byte representation."""
        cstr = self._strings.copy(pass_string(x))
        error.throw_if(len(cstr) < 8)
        return self.from_bytes(cstr[:8])

    def mki(self, x):
        """MKI$: return the byte representation of an int."""
        return self._strings.store(self.to_bytes(self.to_integer(x)))

    def mks(self, x):
        """MKS$: return the byte representation of a single."""
        return self._strings.store(self.to_bytes(self.to_single(x)))

    def mkd(self, x):
        """MKD$: return the byte representation of a double."""
        return self._strings.store(self.to_bytes(self.to_double(x)))

    def representation(self, x):
        """STR$: string representation of a number."""
        return self._strings.store(number_to_str(pass_number(x), screen=True))

    def val(self, x):
        """VAL: number value of a string."""
        return self.str_to_number(self._strings.copy(pass_string(x)))

    def character(self, x):
        """CHR$: character for ASCII value."""
        val = self.to_int(x)
        error.range_check(0, 255, val)
        return self._strings.store(chr(val))

    def octal(self, x):
        """OCT$: octal representation of int."""
        # allow range -32768 to 65535
        val = self.to_integer(x, unsigned=True)
        return self._strings.store(integer_to_str_oct(val))

    def hexadecimal(self, x):
        """HEX$: hexadecimal representation of int."""
        # allow range -32768 to 65535
        val = self.to_integer(x, unsigned=True)
        return self._strings.store(integer_to_str_hex(val))


    ######################################################################
    # string manipulation

    def length(self, x):
        """LEN: length of string."""
        return int_to_integer(string_length(pass_string(x)))

    def asc(self, x):
        """ASC: ordinal ASCII value of a character."""
        s = self._strings.copy(pass_string(x))
        error.throw_if(not s)
        return int_to_integer(ord(s[0]))

    def space(self, x):
        """SPACE$: repeat spaces."""
        num = self.to_int(x)
        error.range_check(0, 255, num)
        return self._strings.store(' '*num)

    # FIXME: start is still a Python int
    def instr(self, big, small, start):
        """INSTR: find substring in string."""
        big = self._strings.copy(pass_string(big))
        small = self._strings.copy(pass_string(small))
        if big == '' or start > len(big):
            return null('%')
        # BASIC counts string positions from 1
        find = big[start-1:].find(small)
        if find == -1:
            return null('%')
        return int_to_integer(start + find)

    def mid(self, s, start, num):
        """MID$: get substring."""
        start = self.to_int(start)
        num = self.to_int(num)
        error.range_check(1, 255, start)
        error.range_check(0, 255, num)
        s = self._strings.copy(s)
        if num == 0 or start > len(s):
            return null('$')
        start -= 1
        stop = start + num
        stop = min(stop, len(s))
        return self._strings.store(s[start:stop])

    def left(self, s, stop):
        """LEFT$: get substring at the start of string."""
        s = self._strings.copy(s)
        stop = self.to_int(stop)
        error.range_check(0, 255, stop)
        if stop == 0:
            return null('$')
        stop = min(stop, len(s))
        return self._strings.store(s[:stop])

    def right(self, s, stop):
        """RIGHT$: get substring at the end of string."""
        s = self._strings.copy(s)
        stop = self.to_int(stop)
        error.range_check(0, 255, stop)
        if stop == 0:
            return null('$')
        stop = min(stop, len(s))
        return self._strings.store(s[-stop:])


    ###########################################################################
    # string representation of numbers

    def str_to_number(self, strval, allow_nonnum=True):
        """Convert Python str to BASIC value."""
        ins = StringIO(strval)
        outs = StringIO()
        # skip spaces and line feeds (but not NUL).
        util.skip(ins, (' ', '\n'))
        self.tokenise_number(ins, outs)
        outs.seek(0)
        value = parse_value(outs)
        if not allow_nonnum and util.skip_white(ins) != '':
            # not everything has been parsed - error
            return None
        if not value:
            return null('%')
        return value

    def str_to_type(self, typechar, word):
        """Convert Python str to requested type, be strict about non-numeric chars."""
        if typechar == '$':
            return self._strings.store(word)
        else:
            return self.str_to_number(word, allow_nonnum=False)

    # this should not be in the interface but is quite entangled
    # REFACTOR 1) to produce a string return value rather than write to stream
    # REFACTOR 2) to util.read_numeric_string -> str_to_number
    def tokenise_number(self, ins, outs):
        """Convert Python-string number representation to number token."""
        c = util.peek(ins)
        if not c:
            return
        elif c == '&':
            # handle hex or oct constants
            ins.read(1)
            if util.peek(ins).upper() == 'H':
                # hex constant
                self._tokenise_hex(ins, outs)
            else:
                # octal constant
                self._tokenise_oct(ins, outs)
        elif c in string.digits + '.+-':
            # handle other numbers
            # note GW passes signs separately as a token
            # and only stores positive numbers in the program
            self._tokenise_dec(ins, outs)

    def _tokenise_dec(self, ins, outs):
        """Convert decimal expression in Python string to number token."""
        have_exp = False
        have_point = False
        word = ''
        kill = False
        while True:
            c = ins.read(1).upper()
            if not c:
                break
            elif c in '\x1c\x1d\x1f':
                # ASCII separator chars invariably lead to zero result
                kill = True
            elif c == '.' and not have_point and not have_exp:
                have_point = True
                word += c
            elif c in 'ED' and not have_exp:
                # there's a special exception for number followed by EL or EQ
                # presumably meant to protect ELSE and maybe EQV ?
                if c == 'E' and util.peek(ins).upper() in ('L', 'Q'):
                    ins.seek(-1, 1)
                    break
                else:
                    have_exp = True
                    word += c
            elif c in '-+' and (not word or word[-1] in 'ED'):
                # must be first token or in exponent
                word += c
            elif c in string.digits:
                word += c
            elif c in number_whitespace:
                # we'll remove this later but need to keep it for now
                # so we can reposition the stream on removing trailing whitespace
                word += c
            elif c in '!#' and not have_exp:
                word += c
                break
            elif c == '%':
                # swallow a %, but break parsing
                break
            else:
                ins.seek(-1, 1)
                break
        # ascii separators encountered: zero output
        if kill:
            word = '0'
        # don't claim trailing whitespace
        while len(word)>0 and (word[-1] in number_whitespace):
            word = word[:-1]
            ins.seek(-1,1) # even if c==''
        # remove all internal whitespace
        trimword = ''
        for c in word:
            if c not in number_whitespace:
                trimword += c
        word = trimword
        # write out the numbers
        if len(word) == 1 and word in string.digits:
            # digit
            outs.write(chr(0x11+str_to_int(word)))
        elif (not (have_exp or have_point or word[-1] in '!#') and
                                str_to_int(word) <= 0x7fff and str_to_int(word) >= -0x8000):
            if str_to_int(word) <= 0xff and str_to_int(word) >= 0:
                # one-byte constant
                outs.write(tk.T_BYTE + chr(str_to_int(word)))
            else:
                # two-byte constant
                outs.write(tk.T_INT + str(self.to_bytes(int_to_integer(str_to_int(word)))))
        else:
            mbf = str(self._str_to_float(word)[1])
            if len(mbf) == 4:
                outs.write(tk.T_SINGLE + mbf)
            else:
                outs.write(tk.T_DOUBLE + mbf)

    def _tokenise_hex(self, ins, outs):
        """Convert hex expression in Python string to number token."""
        # pass the H in &H
        ins.read(1)
        word = ''
        while True:
            c = util.peek(ins)
            # hex literals must not be interrupted by whitespace
            if not c or c not in string.hexdigits:
                break
            else:
                word += ins.read(1)
        val = int(word, 16) if word else 0
        outs.write(tk.T_HEX + str(self.to_bytes(int_to_integer(val, unsigned=True))))

    def _tokenise_oct(self, ins, outs):
        """Convert octal expression in Python string to number token."""
        # O is optional, could also be &777 instead of &O777
        if util.peek(ins).upper() == 'O':
            ins.read(1)
        word = ''
        while True:
            c = util.peek(ins)
            # oct literals may be interrupted by whitespace
            if c and c in number_whitespace:
                ins.read(1)
            elif not c or c not in string.octdigits:
                break
            else:
                word += ins.read(1)
        val = int(word, 8) if word else 0
        outs.write(tk.T_OCT + str(self.to_bytes(int_to_integer(val, unsigned=True))))

    def _str_to_float(self, s):
        """Return Float value for Python string."""
        allow_nonnum = True
        found_sign, found_point, found_exp = False, False, False
        found_exp_sign, exp_neg, neg = False, False, False
        exp10, exponent, mantissa, digits, zeros = 0, 0, 0, 0, 0
        is_double, is_single = False, False
        for c in s:
            # ignore whitespace throughout (x = 1   234  56  .5  means x=123456.5 in gw!)
            if c in number_whitespace:
                continue
            # determine sign
            if (not found_sign):
                found_sign = True
                # number has started; if no sign encountered here, sign must be pos.
                if c in '+-':
                    neg = (c == '-')
                    continue
            # parse numbers and decimal points, until 'E' or 'D' is found
            if (not found_exp):
                if c >= '0' and c <= '9':
                    mantissa *= 10
                    mantissa += ord(c)-ord('0')
                    if found_point:
                        exp10 -= 1
                    # keep track of precision digits
                    if mantissa != 0:
                        digits += 1
                        if found_point and c=='0':
                            zeros += 1
                        else:
                            zeros=0
                    continue
                elif c == '.':
                    found_point = True
                    continue
                elif c.upper() in 'DE':
                    found_exp = True
                    is_double = (c.upper() == 'D')
                    continue
                elif c == '!':
                    # makes it a single, even if more than eight digits specified
                    is_single = True
                    break
                elif c == '#':
                    is_double = True
                    break
                else:
                    if allow_nonnum:
                        break
                    return None
            # parse exponent
            elif (not found_exp_sign):
                # exponent has started; if no sign given, it must be pos.
                found_exp_sign = True
                if c in '+-':
                    exp_neg = (c == '-')
                    continue
            if (c >= '0' and c <= '9'):
                exponent *= 10
                exponent += ord(c) - ord('0')
                continue
            else:
                if allow_nonnum:
                    break
                return None
        if exp_neg:
            exp10 -= exponent
        else:
            exp10 += exponent
        # eight or more digits means double, unless single override
        if digits - zeros > 7 and not is_single:
            is_double = True
        return self._float_from_exp10(neg, mantissa, exp10, is_double)

    @float_safe
    def _float_from_exp10(self, neg, mantissa, exp10, is_double):
        """Create floating-point value from mantissa and decomal exponent."""
        cls = fp.Double if is_double else fp.Single
        # isn't this just cls.from_int(-mantissa if neg else mantissa)?
        mbf = cls(neg, mantissa * 0x100, cls.bias).normalise()
        # apply decimal exponent
        while (exp10 < 0):
            mbf.idiv10()
            exp10 += 1
        while (exp10 > 0):
            mbf.imul10()
            exp10 -= 1
        mbf.normalise()
        return fp.pack(mbf)


##############################################################################

def number_to_str(inp, screen=False, write=False):
    """Convert BASIC number to Python str."""
    # screen=False means in a program listing
    # screen=True is used for screen, str$ and sequential files
    if not inp:
        raise error.RunError(error.STX)
    typechar = inp[0]
    if typechar == '%':
        if screen and not write and integer_to_int(inp) >= 0:
            return ' ' + str(integer_to_int(inp))
        else:
            return str(integer_to_int(inp))
    elif typechar == '!':
        return float_to_str(inp, screen, write)
    elif typechar == '#':
        return float_to_str(inp, screen, write)
    else:
        raise error.RunError(error.TYPE_MISMATCH)

def integer_to_str_oct(inp):
    """Convert integer to str in octal representation."""
    if integer_to_int(inp, unsigned=True) == 0:
        return '0'
    else:
        return oct(integer_to_int(inp, unsigned=True))[1:]

def integer_to_str_hex(inp):
    """Convert integer to str in hex representation."""
    return hex(integer_to_int(inp, unsigned=True))[2:].upper()

def str_to_int(s):
    """Return Python int value for Python str, zero if malformed."""
    try:
        return int(s)
    except ValueError:
        return 0

def float_to_str(n_in, screen=False, write=False):
    """Convert BASIC float to Python string."""
    n_in = fp.unpack(n_in)
    # screen=True (ie PRINT) - leading space, no type sign
    # screen='w' (ie WRITE) - no leading space, no type sign
    # default mode is for LIST
    # zero exponent byte means zero
    if n_in.is_zero():
        if screen and not write:
            valstr = ' 0'
        elif write:
            valstr = '0'
        else:
            valstr = '0' + n_in.type_sign
        return valstr
    # print sign
    if n_in.neg:
        valstr = '-'
    else:
        if screen and not write:
            valstr = ' '
        else:
            valstr = ''
    mbf = n_in.copy()
    num, exp10 = mbf.bring_to_range(mbf.lim_bot, mbf.lim_top)
    digitstr = _get_digits(num, digits=mbf.digits, remove_trailing=True)
    # exponent for scientific notation
    exp10 += mbf.digits-1
    if exp10 > mbf.digits-1 or len(digitstr)-exp10 > mbf.digits+1:
        # use scientific notation
        valstr += _scientific_notation(digitstr, exp10, n_in.exp_sign)
    else:
        # use decimal notation
        if screen or write:
            type_sign=''
        else:
            type_sign = n_in.type_sign
        valstr += _decimal_notation(digitstr, exp10, type_sign)
    return valstr

def format_number(value, tokens, digits_before, decimals):
    """Format a number to a format string. For PRINT USING."""
    # illegal function call if too many digits
    if digits_before + decimals > 24:
        raise error.RunError(error.IFC)
    # extract sign, mantissa, exponent
    value = fp.unpack(value)
    # dollar sign, decimal point
    has_dollar, force_dot = '$' in tokens, '.' in tokens
    # leading sign, if any
    valstr, post_sign = '', ''
    if tokens[0] == '+':
        valstr += '-' if value.neg else '+'
    elif tokens[-1] == '+':
        post_sign = '-' if value.neg else '+'
    elif tokens[-1] == '-':
        post_sign = '-' if value.neg else ' '
    else:
        valstr += '-' if value.neg else ''
        # reserve space for sign in scientific notation by taking away a digit position
        if not has_dollar:
            digits_before -= 1
            if digits_before < 0:
                digits_before = 0
            # just one of those things GW does
            #if force_dot and digits_before == 0 and decimals != 0:
            #    valstr += '0'
    # take absolute value
    value.neg = False
    # currency sign, if any
    valstr += '$' if has_dollar else ''
    # format to string
    if '^' in tokens:
        valstr += _format_float_scientific(value, digits_before, decimals, force_dot)
    else:
        valstr += _format_float_fixed(value, decimals, force_dot)
    # trailing signs, if any
    valstr += post_sign
    if len(valstr) > len(tokens):
        valstr = '%' + valstr
    else:
        # filler
        valstr = ('*' if '*' in tokens else ' ') * (len(tokens) - len(valstr)) + valstr
    return valstr



# for to_str
# for numbers, tab and LF are whitespace
number_whitespace = ' \t\n'

# string representations

fp.Single.lim_top = fp.from_bytes(bytearray('\x7f\x96\x18\x98')) # 9999999, highest float less than 10e+7
fp.Single.lim_bot = fp.from_bytes(bytearray('\xff\x23\x74\x94')) # 999999.9, highest float  less than 10e+6
fp.Single.type_sign, fp.Single.exp_sign = '!', 'E'

fp.Double.lim_top = fp.from_bytes(bytearray('\xff\xff\x03\xbf\xc9\x1b\x0e\xb6')) # highest float less than 10e+16
fp.Double.lim_bot = fp.from_bytes(bytearray('\xff\xff\x9f\x31\xa9\x5f\x63\xb2')) # highest float less than 10e+15
fp.Double.type_sign, fp.Double.exp_sign = '#', 'D'


def _just_under(n_in):
    """Return the largest floating-point number less than the given value."""
    # decrease mantissa by one
    return n_in.__class__(n_in.neg, n_in.man - 0x100, n_in.exp)

def _get_digits(num, digits, remove_trailing):
    """Get the digits for an int."""
    pow10 = 10L**(digits-1)
    digitstr = ''
    while pow10 >= 1:
        digit = ord('0')
        while num >= pow10:
            digit += 1
            num -= pow10
        digitstr += chr(digit)
        pow10 /= 10
    if remove_trailing:
        # remove trailing zeros
        while len(digitstr)>1 and digitstr[-1] == '0':
            digitstr = digitstr[:-1]
    return digitstr

def _scientific_notation(digitstr, exp10, exp_sign='E', digits_to_dot=1, force_dot=False):
    """Put digits in scientific E-notation."""
    valstr = digitstr[:digits_to_dot]
    if len(digitstr) > digits_to_dot:
        valstr += '.' + digitstr[digits_to_dot:]
    elif len(digitstr) == digits_to_dot and force_dot:
        valstr += '.'
    exponent = exp10 - digits_to_dot + 1
    valstr += exp_sign
    if exponent < 0:
        valstr += '-'
    else:
        valstr += '+'
    valstr += _get_digits(abs(exponent), digits=2, remove_trailing=False)
    return valstr

def _decimal_notation(digitstr, exp10, type_sign='!', force_dot=False):
    """Put digits in decimal notation."""
    # digits to decimal point
    exp10 += 1
    if exp10 >= len(digitstr):
        valstr = digitstr + '0'*(exp10-len(digitstr))
        if force_dot:
            valstr+='.'
        if not force_dot or type_sign=='#':
            valstr += type_sign
    elif exp10 > 0:
        valstr = digitstr[:exp10] + '.' + digitstr[exp10:]
        if type_sign == '#':
            valstr += type_sign
    else:
        if force_dot:
            valstr = '0'
        else:
            valstr = ''
        valstr += '.' + '0'*(-exp10) + digitstr
        if type_sign == '#':
            valstr += type_sign
    return valstr

def _format_float_scientific(expr, digits_before, decimals, force_dot):
    """Put a float in scientific format."""
    work_digits = digits_before + decimals
    if work_digits > expr.digits:
        # decimal precision of the type
        work_digits = expr.digits
    if expr.is_zero():
        if not force_dot:
            if expr.exp_sign == 'E':
                return 'E+00'
            return '0D+00'  # matches GW output. odd, odd, odd
        digitstr, exp10 = '0'*(digits_before+decimals), 0
    else:
        if work_digits > 0:
            # scientific representation
            lim_bot = _just_under(fp.pow_int(expr.ten, work_digits-1))
        else:
            # special case when work_digits == 0, see also below
            # setting to 0.1 results in incorrect rounding (why?)
            lim_bot = expr.one.copy()
        lim_top = lim_bot.copy().imul10()
        num, exp10 = expr.bring_to_range(lim_bot, lim_top)
        digitstr = _get_digits(num, work_digits, remove_trailing=True)
        if len(digitstr) < digits_before + decimals:
            digitstr += '0' * (digits_before + decimals - len(digitstr))
    # this is just to reproduce GW results for no digits:
    # e.g. PRINT USING "#^^^^";1 gives " E+01" not " E+00"
    if work_digits == 0:
        exp10 += 1
    exp10 += digits_before + decimals - 1
    return _scientific_notation(digitstr, exp10, expr.exp_sign, digits_to_dot=digits_before, force_dot=force_dot)

def _format_float_fixed(expr, decimals, force_dot):
    """Put a float in fixed-point representation."""
    unrounded = fp.mul(expr, fp.pow_int(expr.ten, decimals)) # expr * 10**decimals
    num = unrounded.copy().iround()
    # find exponent
    exp10 = 1
    pow10 = fp.pow_int(expr.ten, exp10) # pow10 = 10L**exp10
    while num.gt(pow10) or num.equals(pow10): # while pow10 <= num:
        pow10.imul10() # pow10 *= 10
        exp10 += 1
    work_digits = exp10 + 1
    diff = 0
    if exp10 > expr.digits:
        diff = exp10 - expr.digits
        num = fp.div(unrounded, fp.pow_int(expr.ten, diff)).iround()  # unrounded / 10**diff
        work_digits -= diff
    num = num.trunc_to_int()
    # argument work_digits-1 means we're getting work_digits==exp10+1-diff digits
    # fill up with zeros
    digitstr = _get_digits(num, work_digits-1, remove_trailing=False) + '0' * diff
    return _decimal_notation(digitstr, work_digits-1-1-decimals+diff, '', force_dot)


##############################################################################

def token_to_value(full_token):
    """Token to value."""
    if not full_token:
        return None
    lead = full_token[0]
    if lead in (tk.T_OCT, tk.T_HEX, tk.T_INT, tk.T_SINGLE, tk.T_DOUBLE):
        return Values.from_bytes(full_token[1:])
    elif lead == tk.T_BYTE:
        return Values.from_bytes(full_token[1:] + '\0')
    elif tk.C_0 <= lead <= tk.C_10:
        return Values.from_bytes(chr(ord(lead)-0x11) + '\0')
    return None

def parse_value(ins):
    """Token to value."""
    return token_to_value(util.read_token(ins))
