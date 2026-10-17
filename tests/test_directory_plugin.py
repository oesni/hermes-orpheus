"""Load the native entry point under a Hermes-style private package name."""
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from pathlib import Path
import yaml


class DirectoryPluginTests(unittest.IsolatedAsyncioTestCase):
    async def test_namespaced_import_registers_manifest_tools_without_pip_package(self):
        root=Path(__file__).resolve().parents[1]
        manifest=yaml.safe_load((root/'plugin.yaml').read_text())
        self.assertEqual(manifest['manifest_version'],2)
        self.assertEqual(manifest['name'],'hermes-orpheus')
        namespace='hermes_plugins'
        name=namespace+'.orpheus_directory_test'
        original_parent=sys.modules.get(namespace)
        if original_parent is None:
            package=types.ModuleType(namespace)
            package.__path__=[]
            sys.modules[namespace]=package
        try:
            spec=importlib.util.spec_from_file_location(name,root/'__init__.py',submodule_search_locations=[str(root)])
            module=importlib.util.module_from_spec(spec)
            sys.modules[name]=module
            spec.loader.exec_module(module)
            self.assertEqual(module.register.__module__,name+'.orpheus.plugin')
            self.assertTrue(sys.modules[name+'.orpheus.config'].__file__.startswith(str(root)))
            with tempfile.TemporaryDirectory() as directory:
                tools={}; cleanups=[]
                class Context:
                    subagent_lifecycle=object()
                    def get_config(self,key,default=None):
                        return directory if key=='state_dir' else None
                    def register_tool(self,**kw): tools[kw['name']]=kw
                    def on_unload(self,callback): cleanups.append(callback)
                try:
                    ignored_home=Path(directory)/'must-not-use-host-profile'
                    with patch.dict(os.environ, {
                        'ORPHEUS_CONFIG': str(ignored_home/'missing-presets.yaml'),
                        'ORPHEUS_DEPLOYMENT': str(ignored_home/'missing-deployment.yaml'),
                        'ORPHEUS_STATE_DIR': str(ignored_home/'state'),
                        'HERMES_HOME': str(ignored_home),
                    }):
                        module.register(Context())
                    self.assertFalse(ignored_home.exists())
                    self.assertEqual(set(tools),set(manifest['provides_tools']))
                    response=json.loads(await tools['orpheus_presets']['handler']({}))
                    self.assertEqual(response['presets'],[])
                finally:
                    for cleanup in cleanups: cleanup()
        finally:
            for key in list(sys.modules):
                if key==name or key.startswith(name+'.'): del sys.modules[key]
            if original_parent is None: sys.modules.pop(namespace,None)
