import typer

from kylinbootlab import __version__

app = typer.Typer(no_args_is_help=True)


@app.callback()
def main() -> None:
    """KylinBootLab controller CLI."""


@app.command()
def version() -> None:
    """Print the KylinBootLab package version."""
    typer.echo(__version__)
