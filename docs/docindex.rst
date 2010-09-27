gae-sessions documentation
==========================

.. toctree::
   :maxdepth: 2

Useful links
------------

 - Please see the README_ for information on how to install and use gae-sessions.
 - `Release Notes`_
 - Comparison_ to other sessions libraries.

.. _README: http://github.com/dound/gae-sessions#readme
.. _Comparison: http://wiki.github.com/dound/gae-sessions/comparison-with-alternative-libraries
.. _Release Notes: http://wiki.github.com/dound/gae-sessions


Detailed gaesessions module Documentation
-----------------------------------------

.. automodule:: gaesessions
   :members: get_current_session, delete_expired_sessions, SessionMiddleware, DjangoSessionMiddleware

.. autoclass:: gaesessions.Session
   :members: clear, ensure_data_loaded, get, get_expiration, has_key, is_active, is_ssl_only, pop, pop_quick, regenerate_id, save, set_quick, start, terminate, __contains__, __delitem__, __getitem__, __iter__, __setitem__

.. autoclass:: gaesessions.SessionModel

Indices and tables
==================

* :ref:`genindex`
* :ref:`search`
