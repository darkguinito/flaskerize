import os
import argparse
from typing import Any, Callable, Dict, List, Optional
from termcolor import colored

from flaskerize.parser import FzArgumentParser


class SchematicRenderer:
    """Render Flaskerize schematics"""

    # Path to schematic files to copy, relative to top-level schematic_path
    DEFAULT_FILES_DIRNAME = "files"

    def __init__(
        self,
        schematic_path: str,
        src_path: str = ".",
        fs_root: str = ".",
        dry_run: bool = False,
    ):
        from jinja2 import Environment
        from flaskerize.fileio import StagedFileSystem

        self.src_path = src_path
        self.schematic_path = schematic_path
        self.schematic_files_path = os.path.join(
            self.schematic_path, self.DEFAULT_FILES_DIRNAME
        )

        self.schema_path = self._get_schema_path()
        self._load_schema()

        self.arg_parser = self._check_get_arg_parser()
        self.env = Environment()
        self.fs = StagedFileSystem(
            src_path=self.src_path, schematic_path=self.schematic_path, dry_run=dry_run
        )
        self.dry_run = dry_run
        self._directories_created: List[str] = []
        self._files_created: List[str] = []
        self._files_deleted: List[str] = []
        self._files_modified: List[str] = []

    def _load_schema(self) -> None:
        if self.schema_path:
            import json

            with open(self.schema_path, "r") as fid:
                self.config = json.load(fid)
        else:
            self.config = {}

    def _get_schema_path(self) -> Optional[str]:

        schema_path = os.path.join(self.schematic_path, "schema.json")
        if not os.path.isfile(schema_path):
            return None
        return schema_path

    def _check_get_arg_parser(
        self, schema_path: Optional[str] = None
    ) -> FzArgumentParser:
        """Load argument parser from schema.json, if provided"""

        return FzArgumentParser(schema=schema_path or self.schema_path)

    def get_static_files(self) -> List[str]:
        """Get list of files to be copied unchanged"""

        from pathlib import Path

        patterns = self.config.get("templateFilePatterns", [])
        all_files = list(str(p) for p in Path(self.schematic_files_path).glob("**/*"))
        filenames = [os.path.relpath(s, self.schematic_files_path) for s in all_files]
        filenames = list(set(filenames) - set(self.get_template_files()))
        return filenames

    def get_template_files(self) -> List[str]:
        """Get list of templated files to be rendered via Jinja"""

        from pathlib import Path

        filenames = []
        patterns = self.config.get("templateFilePatterns", [])
        for pattern in patterns:
            filenames.extend(
                [str(p) for p in Path(self.schematic_files_path).glob(pattern)]
            )
        ignore_filenames = self._get_ignore_files()
        filenames = list(set(filenames) - set(ignore_filenames))
        filenames = [os.path.relpath(s, self.schematic_files_path) for s in filenames]

        return filenames

    def _get_ignore_files(self) -> List[str]:
        from pathlib import Path

        ignore_filenames = []
        ignore_patterns = self.config.get("ignoreFilePatterns", [])
        for pattern in ignore_patterns:
            ignore_filenames.extend(
                [str(p) for p in Path(self.schematic_path).glob(pattern)]
            )
        return ignore_filenames

    # def _get_rel_path(self, full_path: str, rel_to: str) -> str:
    #     full_path = os.path.relpath(full_path, self.schematic_files_path)
    #     outfile = "".join(full_path.rsplit(".template"))
    #     return outfile

    def _generate_outfile(
        self, template_file: str, root: str, context: Optional[Dict] = None
    ) -> str:
        # TODO: remove the redundant parameter template file that is copied
        # outfile_name = self._get_rel_path(full_path=template_file, rel_to=root)
        outfile_name = "".join(template_file.rsplit(".template"))
        # outfile_name = template_file
        # outfile_name = template_file
        print("_generate_outfile outfile = ", outfile_name)
        print("_generate_outfile template_file = ", template_file)
        print("_generate_outfile rel_to = ", root)
        tpl = self.env.from_string(outfile_name)
        if context is None:
            context = {}
        return tpl.render(**context)

    def render_from_file(self, template_path: str, context: Dict) -> None:
        outpath = self._generate_outfile(template_path, self.src_path, context=context)
        outdir, outfile = os.path.split(outpath)
        rendered_outpath = os.path.join(self.src_path, outpath)
        rendered_outdir = os.path.join(rendered_outpath, outdir)

        if outdir and not self.fs.isdir(outdir):

            self._directories_created.append(rendered_outdir)
            if not self.dry_run:
                self.fs.makedirs(outdir)

        # if os.path.isfile(template_path):
        if self.fs.sch_fs.isfile(template_path):
            # TODO: Refactor dry-run and file system interactions to a composable object
            # passed into this class rather than it containing the write logic
            # with open(template_path, "r") as fid:
            with self.fs.sch_fs.open(template_path, "r") as fid:

                tpl = self.env.from_string(fid.read())

                # TODO: change this to drop src_fs and directly consolidate
                if self.fs.src_fs.exists(outpath):
                    self._files_modified.append(rendered_outpath)
                else:
                    self._files_created.append(rendered_outpath)
                with self.fs.open(outpath, "w") as fout:
                    fout.write(tpl.render(**context))

    def copy_static_file(self, filename: str, context: Dict[str, Any]):
        from shutil import copy

        # TODO: can just use filename instead of generating another variable as the
        # pyfilesystem stuff takes care of relative path prefixes. Still need to render
        # through Jinja, however.
        outpath = self._generate_outfile(filename, self.src_path, context=context)
        outdir, outfile = os.path.split(outpath)
        # outdir = outdir or "."

        if outdir and not self.fs.exists(outdir):
            self._directories_created.append(outdir)
            if not self.dry_run:
                # os.makedirs(outdir)
                self.fs.makedirs(outdir)
        if self.fs.src_fs.exists(outpath):
            self._files_modified.append(outpath)
        else:
            self._files_created.append(outpath)
        # if self.fs.sch_fs.isfile(filename):
        self.fs.copy_from_sch(filename, outpath)
        # if not os.path.isdir(os.path.dirname(outpath)):
        #     os.makedirs(os.path.dirname(outpath))
        # copy(filename, outpath)

    def print_summary(self):
        """Print summary of operations performed"""

        print(
            f"""
Flaskerize job summary:

        {colored("Schematic generation successful!", "green")}
        Full schematic path: {colored(self.schematic_path, "yellow")}

        {len(self._directories_created)} directories created
        {len(self._files_created)} files created
        {len(self._files_deleted)} files deleted
        {len(self._files_modified)} files modified
        """
        )
        for dirname in self._directories_created:
            self._print_created(dirname)
        for filename in self._files_created:
            self._print_created(filename)
        for filename in self._files_deleted:
            self._print_deleted(filename)
        for filename in self._files_modified:
            self._print_modified(filename)
        if self.dry_run:
            print(
                f'\n{colored("Dry run (--dry-run) enabled. No files were actually written.", "yellow")}'
            )

    def _print_created(self, value: str) -> None:

        COLOR = "green"
        BASE = "CREATED"
        print(f"{colored(BASE, COLOR)}: {value}")

    def _print_modified(self, value: str) -> None:

        COLOR = "blue"
        BASE = "MODIFIED"
        print(f"{colored(BASE, COLOR)}: {value}")

    def _print_deleted(self, value: str) -> None:

        COLOR = "red"
        BASE = "DELETED"
        print(f"{colored(BASE, COLOR)}: {value}")

    def _load_run_function(self, path: str) -> Callable:
        from importlib.util import spec_from_file_location, module_from_spec

        spec = spec_from_file_location("run", path)

        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        if not hasattr(module, "run"):
            raise ValueError(f"No method 'run' function found in {path}")
        return getattr(module, "run")

    def _load_custom_functions(self, path: str) -> None:
        import os

        from flaskerize import registered_funcs
        from importlib.util import spec_from_file_location, module_from_spec

        if not os.path.exists(path):
            return
        spec = spec_from_file_location("custom_functions", path)

        module = module_from_spec(spec)
        spec.loader.exec_module(module)

        for f in registered_funcs:
            self.env.globals[f.__name__] = f

    def render(self, name: str, args: List[Any]) -> None:
        """Renders the schematic"""

        context = vars(self.arg_parser.parse_args(args))
        if "name" in context:
            raise ValueError(
                "Collision between Flaskerize-reserved parameter "
                "'name' and parameter found in schema.json corresponding "
                f"to {self.schematic_path}"
            )
        context = {**context, "name": name}

        self._load_custom_functions(
            path=os.path.join(self.schematic_path, "custom_functions.py")
        )
        try:
            run = self._load_run_function(
                path=os.path.join(self.schematic_path, "run.py")
            )
        except (ImportError, ValueError, FileNotFoundError) as e:
            run = default_run
        run(renderer=self, context=context)
        self.fs.commit()


def default_run(renderer: SchematicRenderer, context: Dict[str, Any]) -> None:
    """Default run method"""

    template_files = renderer.get_template_files()
    static_files = renderer.get_static_files()

    # TODO: add test that static files are correctly removed from template_files, etc

    for filename in template_files:
        renderer.render_from_file(filename, context=context)
    for filename in static_files:
        renderer.copy_static_file(filename, context=context)
    renderer.print_summary()
