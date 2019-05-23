#=========================================================================
# BehavioralTranslatorL1_test.py
#=========================================================================
# Author : Peitian Pan
# Date   : May 20, 2019
"""Test the level 1 behavioral translator."""

from __future__ import absolute_import, division, print_function

from functools import reduce

from pymtl import *
from pymtl.passes.rtlir.test_utility import do_test
from pymtl.passes.rtlir.translation.behavioral.BehavioralTranslatorL1 import (
    BehavioralTranslatorL1,
)

from .TestBehavioralTranslator import mk_TestBehavioralTranslator


def local_do_test( m ):
  m.elaborate()
  tr = mk_TestBehavioralTranslator(BehavioralTranslatorL1)(m)
  tr.translate_behavioral( m )
  upblk_src = tr.behavioral.upblk_srcs[m]
  decl_freevars = tr.behavioral.decl_freevars[m]
  assert reduce(lambda r, o: r or upblk_src == o, m._ref_upblk_repr, False)
  assert reduce(lambda r, o: r or decl_freevars == o, m._ref_freevar_repr, False)

def test_pymtl_Bits_freevar( do_test ):
  freevar = Bits32( 42 )
  class A( Component ):
    def construct( s ):
      s.out = OutPort( Bits32 )
      @s.update
      def upblk():
        s.out = freevar
  a = A()
  a._ref_upblk_repr = [
"""\
upblk_decls:
  upblk_decl: upblk
""" ]
  a._ref_freevar_repr = [
"""\
freevars:
  freevar: freevar
""" ]
  do_test( a )

def test_pymtl_list_Bits_freevar( do_test ):
  freevar = [ Bits32(42) for _ in xrange(5) ]
  class A( Component ):
    def construct( s ):
      s.out = OutPort( Bits32 )
      @s.update
      def upblk():
        s.out = freevar[2]
  a = A()
  a._ref_upblk_repr = [
"""\
upblk_decls:
  upblk_decl: upblk
""" ]
  a._ref_freevar_repr = [
"""\
freevars:
  freevar: freevar
""" ]
  do_test( a )

def test_pymtl_multi_upblks( do_test ):
  class A( Component ):
    def construct( s ):
      s.out = [ OutPort( Bits32 ) for _ in xrange(5) ]
      @s.update
      def upblk1():
        s.out[0] = Bits32(42)
      @s.update
      def upblk2():
        s.out[1] = Bits32(42)
  a = A()
  a._ref_upblk_repr = [
"""\
upblk_decls:
  upblk_decl: upblk1
  upblk_decl: upblk2
""",
"""\
upblk_decls:
  upblk_decl: upblk2
  upblk_decl: upblk1
""" ]
  a._ref_freevar_repr = [ """freevars:\n""" ]
  do_test( a )

def test_pymtl_multi_freevars( do_test ):
  class A( Component ):
    def construct( s ):
      STATE_IDLE = Bits2(0)
      STATE_WORK = Bits2(1)
      s.out = [ OutPort( Bits2 ) for _ in xrange(5) ]
      @s.update
      def upblk1():
        s.out[0] = STATE_IDLE
      @s.update
      def upblk2():
        s.out[1] = STATE_WORK
  a = A()
  a._ref_upblk_repr = [
"""\
upblk_decls:
  upblk_decl: upblk1
  upblk_decl: upblk2
""",
"""\
upblk_decls:
  upblk_decl: upblk2
  upblk_decl: upblk1
""" ]
  a._ref_freevar_repr = [
"""\
freevars:
  freevar: STATE_IDLE
  freevar: STATE_WORK
""",
"""\
freevars:
  freevar: STATE_WORK
  freevar: STATE_IDLE
""" ]
  do_test( a )
