# Copyright (c) 2011-2014 by California Institute of Technology
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
#
# 3. Neither the name of the California Institute of Technology nor
#    the names of its contributors may be used to endorse or promote
#    products derived from this software without specific prior
#    written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED.  IN NO EVENT SHALL CALTECH
# OR THE CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF
# USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
# ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
# OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF
# SUCH DAMAGE.
#
"""AST subclasses to translate to each syntax of:

  - gr1c: http://slivingston.github.io/gr1c/md_spc_format.html
  - JTLV
  - SMV: http://nusmv.fbk.eu/NuSMV/userman/v21/nusmv_3.html
  - SPIN: http://spinroot.com/spin/Man/ltl.html
          http://spinroot.com/spin/Man/operators.html
  - python (Boolean formulas only)
"""
import logging
logger = logging.getLogger(__name__)
import pprint
import re
from tulip.spec import ast


def make_jtlv_nodes():
    opmap = {
        'False': 'FALSE', 'True': 'TRUE',
        '!': '!',
        '|': '|', '&': '&', '->': '->', '<->': '<->',
        'G': '[]', 'F': '<>', 'X': 'next',
        'U': 'U',
        '<': '<', '<=': '<=', '=': '=', '>=': '>=', '>': '>', '!=': '!='}
    nodes = ast.make_fol_nodes(opmap)

    class Str(nodes.Str):
        def flatten(self, **kw):
            return '({c})'.format(c=self)

    class Var(nodes.Var):
        def flatten(self, env_vars=None, sys_vars=None, **kw):
            v = self.value
            if v in env_vars:
                player = 'e'
            elif v in sys_vars:
                player = 's'
            else:
                raise ValueError('{v} neither env nor sys var'.format(v))
            return '({player}.{value})'.format(player=player, value=v)

    nodes.Str = Str
    nodes.Var = Var
    return nodes


def make_gr1c_nodes(opmap=None):
    if opmap is None:
        opmap = {
            'False': 'False', 'True': 'True',
            '!': '!',
            '|': '|', '&': '&', '->': '->', '<->': '<->',
            'G': '[]', 'F': '<>', 'X': '',
            '<': '<', '<=': '<=', '=': '=',
            '>=': '>=', '>': '>', '!=': '!='}
    nodes = ast.make_fol_nodes(opmap)

    class Var(nodes.Var):
        def flatten(self, prime=None, **kw):
            return '{v}{prime}'.format(
                v=self.value, prime="'" if prime else '')

    class Unary(nodes.Unary):
        def flatten(self, *arg, **kw):
            if self.operator == 'X':
                kw.update(prime=True)
            return super(Unary, self).flatten(*arg, **kw)

    nodes.Var = Var
    nodes.Unary = Unary
    return nodes


def make_slugs_nodes():
    """Simple translation, unisigned arithmetic only.

    For signed arithmetic use Promela instead.
    """
    opmap = {
        'False': 'FALSE', 'True': 'TRUE',
        '!': '!',
        '|': '|', '&': '&', '->': '->', '<->': '<->',
        'G': '[]', 'F': '<>', 'X': '',
        '<': '<', '<=': '<=', '=': '=', '>=': '>=', '>': '>', '!=': '!=',
        '+': '+', '-': '-'}  # linear arithmetic
    return make_gr1c_nodes(opmap)


def make_promela_nodes():
    opmap = dict(ast.OPMAP)
    opmap.update({'True': 'true', 'False': 'false',
                  'G': '[]', 'F': '<>', 'R': 'V', '=': '=='})
    return ast.make_fol_nodes(opmap)


def make_smv_nodes():
    opmap = {'X': 'X', 'G': 'G', 'F': 'F', 'U': 'U', 'R': 'V'}
    return ast.make_fol_nodes(opmap)


def make_python_nodes():
    opmap = {'!': 'not', '&': 'and', '|': 'or',
             '^': '^', '=': '==', '!=': '!=',
             '<': '<', '<': '<', '>=': '>=', '>': '>',
             '+': '+', '-': '-'}
    nodes = ast.make_fol_nodes(opmap)

    class Imp(nodes.Binary):
        def flatten(self, *arg, **kw):
            return '((not ({l})) or {r})'.format(l=self.left, r=self.right)

    class BiImp(nodes.Binary):
        def flatten(self, *arg, **kw):
            return '({l} == {r})'.format(l=self.left, r=self.right)

    nodes.Imp = Imp
    nodes.BiImp = BiImp
    return nodes


lang2nodes = {
    'jtlv': make_jtlv_nodes(),
    'gr1c': make_gr1c_nodes(),
    'slugs': make_slugs_nodes(),
    'promela': make_promela_nodes(),
    'smv': make_smv_nodes(),
    'python': make_python_nodes()}


def _to_jtlv(d):
    """Return specification as list of two strings [assumption, guarantee].

    Format is that of JTLV.  Cf. L{interfaces.jtlv}.
    """
    logger.info('translate to jtlv...')
    f = _jtlv_str
    parts = [f(d['env_init'], 'valid initial env states', ''),
             f(d['env_safety'], 'safety assumption on environment', '[]'),
             f(d['env_prog'], 'justice assumption on environment', '[]<>')]
    assumption = ' & \n'.join(x for x in parts if x)

    parts = [f(d['sys_init'], 'valid initial system states', ''),
             f(d['sys_safety'], 'safety requirement on system', '[]'),
             f(d['sys_prog'], 'progress requirement on system', '[]<>')]
    guarantee = ' & \n'.join(x for x in parts if x)
    return (assumption, guarantee)


def _jtlv_str(m, comment, prefix='[]<>'):
    # no clauses ?
    if not m:
        return ''
    w = list()
    for x in m:
        logger.debug('translate clause: ' + str(x))
        if not x:
            continue
        # collapse any whitespace between any
        # "next" operator that precedes parenthesis
        if prefix == '[]':
            c = re.sub(r'next\s*\(', 'next(', x)
        else:
            c = x
        w.append('\t{prefix}({formula})'.format(prefix=prefix, formula=c))
    return '-- {comment}\n{formula}'.format(
        comment=comment, formula=' & \n'.join(w))


def _to_gr1c(d):
    """Dump to gr1c specification string.

    Cf. L{interfaces.gr1c}.
    """
    def _to_gr1c_print_vars(vardict):
        output = ''
        for var, dom in vardict.iteritems():
            if dom == 'boolean':
                output += ' ' + var
            elif isinstance(dom, tuple) and len(dom) == 2:
                output += ' %s [%d, %d]' % (var, dom[0], dom[1])
            elif isinstance(dom, list) and len(dom) > 0:
                int_dom = convert_domain(dom)
                output += ' %s [%d, %d]' % (var, int_dom[0], int_dom[1])
            else:
                raise ValueError(
                    'Domain "{dom}" not supported by gr1c.'.format(dom=dom))
        return output

    logger.info('translate to gr1c...')
    output = (
        'ENV:' + _to_gr1c_print_vars(d['env_vars']) + ';\n' +
        'SYS:' + _to_gr1c_print_vars(d['sys_vars']) + ';\n' +

        _gr1c_str(d['env_init'], 'ENVINIT', '') +
        _gr1c_str(d['env_safety'], 'ENVTRANS', '[]') +
        _gr1c_str(d['env_prog'], 'ENVGOAL', '[]<>') + '\n' +

        _gr1c_str(d['sys_init'], 'SYSINIT', '') +
        _gr1c_str(d['sys_safety'], 'SYSTRANS', '[]') +
        _gr1c_str(d['sys_prog'], 'SYSGOAL', '[]<>')
    )
    return output


# currently also used in interfaces.jtlv
# eliminate it from there
def convert_domain(dom):
    """Return equivalent integer domain if C{dom} contais strings.

    @type dom: C{list} of C{str}
    @rtype: C{'boolean'} or C{(min_int, max_int)}
    """
    # not a string variable ?
    if not isinstance(dom, list):
        return dom
    return (0, len(dom) - 1)


def _gr1c_str(s, name='SYSGOAL', prefix='[]<>'):
    if not s:
        return '{name}:;\n'.format(name=name)
    f = '\n& '.join([
        prefix + '({u})'.format(u=x) for x in s])
    return '{name}: {f};\n'.format(name=name, f=f)


def _to_slugs(d):
    """Return structured slugs spec.

    @type spec: L{GRSpec}.
    """
    f = _slugs_str
    return (
        _format_slugs_vars(d['env_vars'], 'INPUT') +
        _format_slugs_vars(d['sys_vars'], 'OUTPUT') +

        f(d['env_safety'], 'ENV_TRANS') +
        f(d['env_prog'], 'ENV_LIVENESS') +
        f(d['env_init'], 'ENV_INIT', sep='&') +

        f(d['sys_safety'], 'SYS_TRANS') +
        f(d['sys_prog'], 'SYS_LIVENESS') +
        f(d['sys_init'], 'SYS_INIT', sep='&')
    )


def _slugs_str(r, name, sep='\n'):
    if not r:
        return '[{name}]\n'.format(name=name)
    sep = ' {sep} '.format(sep=sep)
    f = sep.join(x for x in r if x)
    return '[{name}]\n{f}\n\n'.format(name=name, f=f)


def _format_slugs_vars(vardict, name):
    a = []
    for var, dom in vardict.iteritems():
        if dom == 'boolean':
            a.append(var)
        elif isinstance(dom, tuple) and len(dom) == 2:
            a.append('{var}: {min}...{max}'.format(
                var=var, min=dom[0], max=dom[1])
            )
        else:
            raise ValueError('unknown domain type: {dom}'.format(dom=dom))
    return '[{name}]\n{vars}\n\n'.format(name=name, vars='\n'.join(a))


to_lang = {'jtlv': _to_jtlv, 'gr1c': _to_gr1c, 'slugs': _to_slugs}


def translate(spec, lang):
    """Return str in tool format.

    @type spec: L{GRSpec}
    @type lang: 'gr1c' or 'slugs' or 'jtlv'

    @return: spec formatted for input to tool
    @rtype: C{str}
    """
    spec.str_to_int()
    pprint.pprint(spec._bool_int)
    d = {p: [translate_ast(spec.ast(spec._bool_int[x]), lang).flatten(
             env_vars=spec.env_vars, sys_vars=spec.sys_vars)
         for x in getattr(spec, p)] for p in spec._parts}
    pprint.pprint(d)
    d['env_vars'] = spec.env_vars
    d['sys_vars'] = spec.sys_vars
    return to_lang[lang](d)


def translate_ast(tree, lang):
    """Return AST of formula C{tree}.

    @type tree: L{Nodes.Node}
    @type lang: 'gr1c' or 'slugs' or 'jtlv' or
      'promela' or 'smv' or 'python'

    @return: tree using AST nodes of C{lang}
    @rtype: L{FOL.Node}
    """
    if lang == 'python':
        return _ast_to_python(tree, lang2nodes[lang])
    else:
        return _ast_to_lang(tree, lang2nodes[lang])


def _ast_to_lang(u, nodes):
    cls = getattr(nodes, type(u).__name__)
    if isinstance(u, ast.nodes.Terminal):
        return cls(u.value)
    elif isinstance(u, ast.nodes.Unary):
        x = _ast_to_lang(u.operand, nodes)
        return cls(u.operator, x)
    elif isinstance(u, ast.nodes.Binary):
        x = _ast_to_lang(u.left, nodes)
        y = _ast_to_lang(u.right, nodes)
        return cls(u.operator, x, y)


def _ast_to_python(u, nodes):
    cls = getattr(nodes, type(u).__name__)
    if isinstance(u, ast.nodes.Terminal):
        return cls(u.value)
    elif isinstance(u, ast.nodes.Unary):
        assert u.operator == '!'
        return cls(u.operator, _ast_to_lang(u.operand))
    elif isinstance(u, ast.nodes.Binary):
        assert u.operator in {'&', '|', '^', '=', '->', '<->'}
        if u.operator == '->':
            cls = nodes.Imp
        elif u.operator == '<->':
            cls = nodes.BiImp
        return cls(u.operator, _ast_to_lang(u.left), _ast_to_lang(u.right))