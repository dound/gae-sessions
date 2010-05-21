def generate_coverage():
    import coverage
    cov = coverage.coverage()
    cov.load()
    cov.start()
    import gaesessions, main, SessionTester  # our nose tests miss the import lines
    cov.stop()
    cov.save()
    cov.html_report(directory="covhtml", omit_prefixes=["/usr","webtest"])

if __name__ == '__main__': generate_coverage()
