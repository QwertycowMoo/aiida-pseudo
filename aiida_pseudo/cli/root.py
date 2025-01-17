# -*- coding: utf-8 -*-
"""Command line interface `aiida-pseudo`."""
import click

from aiida.cmdline.params import options, types


@click.group('aiida-pseudo', context_settings={'help_option_names': ['-h', '--help']})
@options.PROFILE(type=types.ProfileParamType(load_profile=True))
def cmd_root(profile):  # pylint: disable=unused-argument
    """CLI for the ``aiida-pseudo`` plugin."""
