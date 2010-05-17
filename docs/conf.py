# gae-sessions documentation build configuration file

import sys, os
sys.path.append(os.path.abspath('../'))

extensions = ['sphinx.ext.autodoc']
templates_path = []
source_suffix = '.rst'
master_doc = 'docindex'
project = u'gae-sessions'
copyright = u'2010, David Underhill'
release = version = '0.9'
exclude_trees = ['_build']

pygments_style = 'sphinx'
html_theme = 'default'
html_static_path = []
htmlhelp_basename = 'gae-sessionsdoc'

latex_documents = [
  ('index', 'gae-sessions.tex', u'gae-sessions Documentation',
   u'David Underhill', 'manual'),
]
