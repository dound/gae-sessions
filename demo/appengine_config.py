from gaesessions import SessionMiddleware

def webapp_add_wsgi_middleware(app):
  from google.appengine.ext.appstats import recording
  app = SessionMiddleware(app)
  app = recording.appstats_wsgi_middleware(app)
  return app
