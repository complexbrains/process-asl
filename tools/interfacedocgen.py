"""Attempt to generate templates for module reference with Sphinx
XXX - we exclude extension modules
To include extension modules, first identify them as valid in the
``_uri2path`` method, then handle them in the ``_parse_module`` script.
We get functions and classes by parsing the text of .py files.
Alternatively we could import the modules for discovery, and we'd have
to do that for extension modules.  This would involve changing the
``_parse_module`` method to work via import and introspection, and
might involve changing ``discover_modules`` (which determines which
files are modules, and therefore which module URIs will be passed to
``_parse_module``).
NOTE: this is a modified version of a script originally shipped with the
PyMVPA project, which we've adapted for NIPY use.  PyMVPA is an MIT-licensed
project."""

from __future__ import print_function
#from builtins import object

# Stdlib imports
import inspect
import os
import re
import sys
import tempfile
import warnings

from nipype.interfaces.base import BaseInterface
from nipype.pipeline.engine import Workflow
from nipype.utils.misc import trim

#from github import get_file_url
def get_file_url(arg):
    pass

# Functions and classes


class InterfaceHelpWriter(object):
    ''' Class for automatic detection and parsing of API docs
    to Sphinx-parsable reST format'''

    # only separating first two levels
    rst_section_levels = ['*', '=', '-', '~', '^']

    def __init__(self,
                 package_name,
                 rst_extension='.rst',
                 package_skip_patterns=None,
                 module_skip_patterns=None,
                 class_skip_patterns=None
                 ):
        ''' Initialize package for parsing
        Parameters
        ----------
        package_name : string
            Name of the top-level package.  *package_name* must be the
            name of an importable package
        rst_extension : string, optional
            Extension for reST files, default '.rst'
        package_skip_patterns : None or sequence of {strings, regexps}
            Sequence of strings giving URIs of packages to be excluded
            Operates on the package path, starting at (including) the
            first dot in the package path, after *package_name* - so,
            if *package_name* is ``sphinx``, then ``sphinx.util`` will
            result in ``.util`` being passed for earching by these
            regexps.  If is None, gives default. Default is:
            ['\.tests$']
        module_skip_patterns : None or sequence
            Sequence of strings giving URIs of modules to be excluded
            Operates on the module name including preceding URI path,
            back to the first dot after *package_name*.  For example
            ``sphinx.util.console`` results in the string to search of
            ``.util.console``
            If is None, gives default. Default is:
            ['\.setup$', '\._']
        class_skip_patterns : None or sequence
            Sequence of strings giving classes to be excluded
            Default is: None
        '''
        if package_skip_patterns is None:
            package_skip_patterns = ['\\.tests$']
        if module_skip_patterns is None:
            module_skip_patterns = ['\\.setup$', '\\._']
        if class_skip_patterns:
            self.class_skip_patterns = class_skip_patterns
        else:
            self.class_skip_patterns = []
        self.package_name = package_name
        self.rst_extension = rst_extension
        self.package_skip_patterns = package_skip_patterns
        self.module_skip_patterns = module_skip_patterns

    def get_package_name(self):
        return self._package_name

    def set_package_name(self, package_name):
        ''' Set package_name
        >>> docwriter = ApiDocWriter('sphinx')
        >>> import sphinx
        >>> docwriter.root_path == sphinx.__path__[0]
        True
        >>> docwriter.package_name = 'docutils'
        >>> import docutils
        >>> docwriter.root_path == docutils.__path__[0]
        True
        '''
        # It's also possible to imagine caching the module parsing here
        self._package_name = package_name
        self.root_module = __import__(package_name)
        self.root_path = self.root_module.__path__[0]
        self.written_modules = None

    package_name = property(get_package_name, set_package_name, None,
                            'get/set package_name')

    def _get_object_name(self, line):
        ''' Get second token in line
        >>> docwriter = ApiDocWriter('sphinx')
        >>> docwriter._get_object_name("  def func():  ")
        'func'
        >>> docwriter._get_object_name("  class Klass(object):  ")
        'Klass'
        >>> docwriter._get_object_name("  class Klass:  ")
        'Klass'
        '''
        name = line.split()[1].split('(')[0].strip()
        # in case we have classes which are not derived from object
        # ie. old style classes
        return name.rstrip(':')

    def _uri2path(self, uri):
        ''' Convert uri to absolute filepath
        Parameters
        ----------
        uri : string
            URI of python module to return path for
        Returns
        -------
        path : None or string
            Returns None if there is no valid path for this URI
            Otherwise returns absolute file system path for URI
        Examples
        --------
        >>> docwriter = ApiDocWriter('sphinx')
        >>> import sphinx
        >>> modpath = sphinx.__path__[0]
        >>> res = docwriter._uri2path('sphinx.builder')
        >>> res == os.path.join(modpath, 'builder.py')
        True
        >>> res = docwriter._uri2path('sphinx')
        >>> res == os.path.join(modpath, '__init__.py')
        True
        >>> docwriter._uri2path('sphinx.does_not_exist')
        '''
        if uri == self.package_name:
            return os.path.join(self.root_path, '__init__.py')
        path = uri.replace('.', os.path.sep)
        path = path.replace(self.package_name + os.path.sep, '')
        path = os.path.join(self.root_path, path)
        # XXX maybe check for extensions as well?
        if os.path.exists(path + '.py'):  # file
            path += '.py'
        elif os.path.exists(os.path.join(path, '__init__.py')):
            path = os.path.join(path, '__init__.py')
        else:
            return None
        return path

    def _path2uri(self, dirpath):
        ''' Convert directory path to uri '''
        relpath = dirpath.replace(self.root_path, self.package_name)
        if relpath.startswith(os.path.sep):
            relpath = relpath[1:]
        return relpath.replace(os.path.sep, '.')

    def _parse_module(self, uri):
        ''' Parse module defined in *uri* '''
        filename = self._uri2path(uri)
        if filename is None:
            # nothing that we could handle here.
            return ([], [])
        f = open(filename, 'rt')
        functions, classes = self._parse_lines(f, uri)
        f.close()
        return functions, classes

    def _parse_lines(self, linesource, module):
        ''' Parse lines of text for functions and classes '''
        functions = []
        classes = []
        for line in linesource:
            if line.startswith('def ') and line.count('('):
                # exclude private stuff
                name = self._get_object_name(line)
                if not name.startswith('_'):
                    functions.append(name)
            elif line.startswith('class '):
                # exclude private stuff
                name = self._get_object_name(line)
                if not name.startswith('_') and \
                        self._survives_exclude('.'.join((module, name)),
                                               'class'):
                    classes.append(name)
            else:
                pass
        functions.sort()
        classes.sort()
        return functions, classes

    def _write_graph_section(self, fname, title):
        ad = '\n%s\n%s\n\n' % (title, self.rst_section_levels[3] * len(title))
        ad += '.. graphviz::\n\n'
        fhandle = open(fname)
        for line in fhandle:
            ad += '\t' + line + '\n'

        fhandle.close()
        os.remove(fname)
        os.remove(fname + ".png")
        return ad

    def generate_api_doc(self, uri):
        '''Make autodoc documentation template string for a module
        Parameters
        ----------
        uri : string
            python location of module - e.g 'sphinx.builder'
        Returns
        -------
        S : string
            Contents of API doc
        '''
        # get the names of all classes and functions
        functions, classes = self._parse_module(uri)
        # edit only Classes documentation
        functions = []
        workflows = []
        helper_functions = []
        for function in functions:

            try:
                __import__(uri)
                finst = sys.modules[uri].__dict__[function]
            except TypeError:
                continue
            try:
                workflow = finst()
            except Exception:
                helper_functions.append((function, finst))
                continue

            if isinstance(workflow, Workflow):
                workflows.append((workflow, function, finst))

        if not classes and not workflows and not helper_functions:
            print('WARNING: Empty -', uri)  # dbg
            return ''

        # Make a shorter version of the uri that omits the package name for
        # titles
        uri_short = re.sub(r'^%s\.' % self.package_name, '', uri)
        # uri_short = uri

        ad = '.. AUTO-GENERATED FILE -- DO NOT EDIT!\n\n'

        chap_title = uri_short
        ad += (chap_title + '\n' +
               self.rst_section_levels[1] * len(chap_title) + '\n\n')

        # Set the chapter title to read 'module' for all modules except for the
        # main packages
        # if '.' in uri:
        #    title = 'Module: :mod:`' + uri_short + '`'
        # else:
        #    title = ':mod:`' + uri_short + '`'
        # ad += title + '\n' + self.rst_section_levels[2] * len(title)

        # ad += '\n' + 'Classes' + '\n' + \
        #    self.rst_section_levels[2] * 7 + '\n'
        for c in classes:
            __import__(uri)
            print(c)
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    classinst = sys.modules[uri].__dict__[c]
            except Exception as inst:
                print(inst)
                continue

            if not issubclass(classinst, BaseInterface):
                continue

            label = uri + '.' + c + ':'
            ad += '\n.. _%s\n\n' % label
            ad += '\n.. index:: %s\n\n' % c
            ad += c + '\n' + self.rst_section_levels[2] * len(c) + '\n\n'
            ad += "`Link to code <%s>`__\n\n" % get_file_url(classinst)
            ad += trim(classinst.help(returnhelp=True),
                       self.rst_section_levels[3]) + '\n'

        if workflows or helper_functions:
            ad += '\n.. module:: %s\n\n' % uri

        for workflow, name, finst in workflows:
            label = ':func:`' + name + '`'
            ad += '\n.. _%s:\n\n' % (uri + '.' + name)
            ad += '\n'.join((label, self.rst_section_levels[2] * len(label)))
            ad += "\n\n`Link to code <%s>`__\n\n" % get_file_url(finst)
            helpstr = trim(finst.__doc__, self.rst_section_levels[3])
            ad += '\n\n' + helpstr + '\n\n'

            """
            # use sphinx autodoc for function signature
            ad += '\n.. _%s:\n\n' % (uri + '.' + name)
            ad += '.. autofunction:: %s\n\n' % name
            """

            (_, fname) = tempfile.mkstemp(suffix=".dot")
            workflow.write_graph(dotfilename=fname, graph2use='hierarchical')

            ad += self._write_graph_section(fname, 'Graph') + '\n'

        for name, finst in helper_functions:
            label = ':func:`' + name + '`'
            ad += '\n.. _%s:\n\n' % (uri + '.' + name)
            ad += '\n'.join((label, self.rst_section_levels[2] * len(label)))
            ad += "\n\n`Link to code <%s>`__\n\n" % get_file_url(finst)
            helpstr = trim(finst.__doc__, self.rst_section_levels[3])
            ad += '\n\n' + helpstr + '\n\n'

        return ad

    def _survives_exclude(self, matchstr, match_type):
        ''' Returns True if *matchstr* does not match patterns
        ``self.package_name`` removed from front of string if present
        Examples
        --------
        >>> dw = ApiDocWriter('sphinx')
        >>> dw._survives_exclude('sphinx.okpkg', 'package')
        True
        >>> dw.package_skip_patterns.append('^\\.badpkg$')
        >>> dw._survives_exclude('sphinx.badpkg', 'package')
        False
        >>> dw._survives_exclude('sphinx.badpkg', 'module')
        True
        >>> dw._survives_exclude('sphinx.badmod', 'module')
        True
        >>> dw.module_skip_patterns.append('^\\.badmod$')
        >>> dw._survives_exclude('sphinx.badmod', 'module')
        False
        '''
        if match_type == 'module':
            patterns = self.module_skip_patterns
        elif match_type == 'package':
            patterns = self.package_skip_patterns
        elif match_type == 'class':
            patterns = self.class_skip_patterns
        else:
            raise ValueError('Cannot interpret match type "%s"'
                             % match_type)
        # Match to URI without package name
        L = len(self.package_name)
        if matchstr[:L] == self.package_name:
            matchstr = matchstr[L:]
        for pat in patterns:
            try:
                pat.search
            except AttributeError:
                pat = re.compile(pat)
            if pat.search(matchstr):
                return False
        return True

    def discover_modules(self):
        ''' Return module sequence discovered from ``self.package_name``
        Parameters
        ----------
        None
        Returns
        -------
        mods : sequence
            Sequence of module names within ``self.package_name``
        Examples
        --------
        >>> dw = ApiDocWriter('sphinx')
        >>> mods = dw.discover_modules()
        >>> 'sphinx.util' in mods
        True
        >>> dw.package_skip_patterns.append('\.util$')
        >>> 'sphinx.util' in dw.discover_modules()
        False
        >>>
        '''
        modules = [self.package_name]
        # raw directory parsing
        for dirpath, dirnames, filenames in os.walk(self.root_path):
            # Check directory names for packages
            root_uri = self._path2uri(os.path.join(self.root_path,
                                                   dirpath))
            for dirname in dirnames[:]:  # copy list - we modify inplace
                package_uri = '.'.join((root_uri, dirname))
                if (self._uri2path(package_uri) and
                        self._survives_exclude(package_uri, 'package')):
                    modules.append(package_uri)
                else:
                    dirnames.remove(dirname)
            # Check filenames for modules
            for filename in filenames:
                module_name = filename[:-3]
                module_uri = '.'.join((root_uri, module_name))
                if (self._uri2path(module_uri) and
                        self._survives_exclude(module_uri, 'module')):
                    modules.append(module_uri)
        return sorted(modules)

    def write_modules_api(self, modules, outdir):
        # write the list
        written_modules = []
        for m in modules:
            api_str = self.generate_api_doc(m)
            if not api_str:
                continue
            api_str.replace('nipype', '')
            print('nipype' in api_str)
            # write out to file
            outfile = os.path.join(outdir,
                                   m + self.rst_extension)
            fileobj = open(outfile, 'wt')
            fileobj.write(api_str)
            fileobj.close()
            written_modules.append(m)
        self.written_modules = written_modules

    def write_api_docs(self, outdir):
        """Generate API reST files.
        Parameters
        ----------
        outdir : string
            Directory name in which to store files
            We create automatic filenames for each module
        Returns
        -------
        None
        Notes
        -----
        Sets self.written_modules to list of written modules
        """
        if not os.path.exists(outdir):
            os.mkdir(outdir)
        # compose list of modules
        modules = self.discover_modules()
        self.write_modules_api(modules, outdir)

    def write_index(self, outdir, froot='gen', relative_to=None):
        """Make a reST API index file from written files
        Parameters
        ----------
        path : string
            Filename to write index to
        outdir : string
            Directory to which to write generated index file
        froot : string, optional
            root (filename without extension) of filename to write to
            Defaults to 'gen'.  We add ``self.rst_extension``.
        relative_to : string
            path to which written filenames are relative.  This
            component of the written file path will be removed from
            outdir, in the generated index.  Default is None, meaning,
            leave path as it is.
        """
        if self.written_modules is None:
            raise ValueError('No modules written')
        # Get full filename path
        path = os.path.join(outdir, froot + self.rst_extension)
        # Path written into index is relative to rootpath
        if relative_to is not None:
            relpath = outdir.replace(relative_to + os.path.sep, '')
        else:
            relpath = outdir
        idx = open(path, 'wt')
        w = idx.write
        w('.. AUTO-GENERATED FILE -- DO NOT EDIT!\n\n')
        w('.. toctree::\n')
        w('   :maxdepth: 2\n\n')
        for f in self.written_modules:
            w('   %s\n' % os.path.join(relpath, f))
        idx.close()