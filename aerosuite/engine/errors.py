"""Engine error types. Messages are written for the end user and shown as-is."""


class AeroSuiteError(Exception):
    """Base class for every error the engine raises on purpose."""


class ProjectError(AeroSuiteError):
    """A project folder, project.json or mesh could not be used."""


class TemplateError(AeroSuiteError):
    """The master .cfg template is missing or unreadable."""


class GenerationError(AeroSuiteError):
    """Case names or config files cannot be generated."""


class JobError(AeroSuiteError):
    """A job could not be started, refreshed or cancelled."""
