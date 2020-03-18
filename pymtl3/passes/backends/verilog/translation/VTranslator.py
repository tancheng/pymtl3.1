#=========================================================================
# VTranslator.py
#=========================================================================
# Author : Peitian Pan
# Date   : March 15, 2019
"""Provide SystemVerilog translator."""

from collections import deque

from pymtl3.passes.backends.generic import RTLIRTranslator
from pymtl3.passes.backends.verilog.errors import VerilogStructuralTranslationError
from pymtl3.passes.backends.verilog.util.utility import verilog_reserved

from .behavioral import VBehavioralTranslator as V_BTranslator
from .structural import VStructuralTranslator as V_STranslator
from ..VerilogPlaceholderPass import VerilogPlaceholderPass


def mk_VTranslator( _RTLIRTranslator, _STranslator, _BTranslator ):

  class _VTranslator( _RTLIRTranslator, _STranslator, _BTranslator ):

    def get_pretty( s, namespace, attr, newline=True ):
      ret = getattr(namespace, attr, "")
      if newline and (ret and ret[-1] != '\n'):
        ret += "\n"
      return ret

    def is_verilog_reserved( s, name ):
      return name in verilog_reserved

    def set_header( s ):
      s.header = \
"""\
//-------------------------------------------------------------------------
// {name}.v
//-------------------------------------------------------------------------
// This file is generated by PyMTL SystemVerilog translation pass.

"""

    def rtlir_tr_initialize( s ):
      # Unpacked array indice that will be pushed to the end of signal expr
      s._rtlir_tr_unpacked_q = deque()
      s._placeholder_pass = VerilogPlaceholderPass
      s._mangled_placeholder_top_module_name = ''
      s._included_pickled_files = set()

    def rtlir_tr_src_layout( s, hierarchy ):
      # Sanity check on BitStructs
      all_structs = list(map(lambda x: x[0], hierarchy.decl_type_struct))
      all_struct_names = list(map(lambda x: x.cls.__name__, all_structs))
      for struct in all_structs:
        for field_name in struct.get_all_properties().keys():
          if field_name in all_struct_names:
            raise VerilogStructuralTranslationError(struct,
              f'field {field_name} has the same name as BitStruct type {field_name}!')

      s.set_header()
      name = s._top_module_full_name
      ret = s.header.format( **locals() )

      # Add struct definitions
      for struct_dtype, tplt in hierarchy.decl_type_struct:
        template = \
"""\
// PyMTL BitStruct {dtype_name} Definition
// At {file_info}
{struct_def}\
"""
        dtype_name = struct_dtype.get_name()
        file_info = struct_dtype.get_file_info()
        struct_def = tplt['def'] + '\n'
        ret += template.format( **locals() )

      # Add component sources
      ret += hierarchy.component_src
      return ret

    def rtlir_tr_components( s, components ):
      return "\n\n".join( components )

    def rtlir_tr_component( s, behavioral, structural ):
      component_name = structural.component_name
      file_info = structural.component_file_info
      full_name = structural.component_full_name

      if structural.component_explicit_module_name:
        module_name = \
            structural.component_explicit_module_name
      elif structural.component_is_top and s._mangled_placeholder_top_module_name:
        module_name = s._mangled_placeholder_top_module_name
      else:
        module_name = structural.component_unique_name

      if structural.component_no_synthesis:
        no_synth_begin = '`ifndef SYNTHESIS\n'
        no_synth_end   = '`endif'
      else:
        no_synth_begin = ''
        no_synth_end   = ''

      s._top_module_name = structural.component_name
      s._top_module_full_name = module_name

      if full_name != module_name:
        optional_full_name = f"Full name: {full_name}\n// "
      else:
        optional_full_name = ""

      if structural.placeholder_src:
        # This is a placeholder
        placeholder_src = structural.placeholder_src
        template = \
"""\
// PyMTL Placeholder {component_name} Definition
// {optional_full_name}At {file_info}

{no_synth_begin}{placeholder_src}
{no_synth_end}"""
        return template.format( **locals() )

      else:
        template = \
"""\
// PyMTL Component {component_name} Definition
// {optional_full_name}At {file_info}

{no_synth_begin}module {module_name}
(
{ports});
{body}
endmodule
{no_synth_end}"""
        ports_template = "{port_decls}{ifc_decls}"

        port_decls = s.get_pretty(structural, 'decl_ports', False)
        ifc_decls = s.get_pretty(structural, 'decl_ifcs', False)
        if port_decls or ifc_decls:
          if port_decls and ifc_decls:
            port_decls += ',\n'
          ifc_decls += '\n'
        ports = ports_template.format(**locals())

        const_decls = s.get_pretty(structural, "decl_consts")
        fvar_decls = s.get_pretty(behavioral, "decl_freevars")
        wire_decls = s.get_pretty(structural, "decl_wires")
        tmpvar_decls = s.get_pretty(behavioral, "decl_tmpvars")
        subcomp_decls = s.get_pretty(structural, "decl_subcomps")
        upblk_decls = s.get_pretty(behavioral, "upblk_decls")
        body = const_decls + fvar_decls + wire_decls + subcomp_decls \
             + tmpvar_decls + upblk_decls
        connections = s.get_pretty(structural, "connections")
        if (body and connections) or (not body and connections):
          connections = '\n' + connections
        body += connections

        return template.format( **locals() )

  return _VTranslator

VTranslator = mk_VTranslator( RTLIRTranslator, V_STranslator, V_BTranslator )
