
class PrettyLogger:

    def __init__(self, logger):
        self.logger = logger

    def separator(self, length=80, char="-"):
        self.logger.info(char * length)

    def header(self, text, length=80):

        line = "-" * length

        self.logger.info(
            "%s\n%s\n%s",
            line,
            text,
            line
        )

    def banner(self, text, length=80):

        line = "=" * length

        self.logger.info(
            "\n%s\n%s\n%s",
            line,
            text.upper(),
            line
        )