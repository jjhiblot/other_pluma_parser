import difflib
import copy
import random
import os
import sys
from os import path
from typing import Any, IO
import yaml
from collections.abc import Iterable
from collections.abc import Hashable

global_context = {"board":"EVK", "overrides": ['evk', 'seb','imx8mm'], "DUT_IP":"192.168.1.29", "HOST_IP":"192.168.1.41", "mem_size":1992}

class PathFinder:
    '''class holding the list of directories to be searched when looking for a file'''
    paths = []

    @staticmethod
    def add(path: str):
        PathFinder.paths.append(path)

    @staticmethod
    def locate(filename: str, current_dir: str = None) -> str:
        filename = str(filename)
        if path.isabs(filename):
            # print(f"Found {filename}")
            return filename
        l = [current_dir] if current_dir else []
        if PathFinder.paths:
            l.extend(PathFinder.paths)
        for d in l:
            p = path.join(d, filename)
            if path.exists(p):
                # print(f"Found {p}")
                return p
        # print(f"Did not find {p}")
        return None

    @staticmethod
    def locateall(filename: str, current_dir: str = None) -> str:
        filename = str(filename)
        result = []
        if path.isabs(filename):
            # print(f"Found {[filename]}")
            return [filename]
        l = [current_dir] if current_dir else []
        if PathFinder.paths:
            l.extend(PathFinder.paths)
        for d in l:
            p = path.join(d, filename)
            if path.exists(p):
                result.append(p)
        # print(f"Found {result}")
        return result


class OverrideDict(dict):
    def get(self, name, default=None):
        global global_context
        for ov in global_context["overrides"]:
            nk = name + '_' + ov
            if nk in self:
                return self[nk]
        return super().get(name, default)


class YmlObject:
    def __init__(self):
        self.name = self.__class__
        self.parent = None

    @staticmethod
    def update_children_params(obj, update):
        if isinstance(obj, dict):
            for k in obj:
                YmlObject.update_children_params(obj[k], update)
        elif isinstance(obj, list):
            for e in obj:
                YmlObject.update_children_params(e, update)
        elif isinstance(obj, YmlObject):
            obj.update_params(update)
        elif isinstance(obj, LazyStr):
            obj.update_context(update)
        elif isinstance(obj, LazyEvaluator):
            obj.update_context(update)

    def update_params(self, update):
        self.parameters.update(update)
        for member in dir(self):
            if member.startswith('__') and member.endswith('__'):
                continue
            if member == "parent":
                continue
            YmlObject.update_children_params(getattr(self, member), update)

    @staticmethod
    def post_init_children(obj, parent):
        if isinstance(obj, dict):
            for k in obj:
                YmlObject.post_init_children(obj[k], parent)
        elif isinstance(obj, list):
            for e in obj:
                YmlObject.post_init_children(e, parent)
        elif isinstance(obj, YmlObject):
            obj.post_init(parent)
        elif isinstance(obj, LazyStr):
            obj.update_context(parent.parameters)
        elif isinstance(obj, LazyEvaluator):
            obj.update_context(parent.parameters)

    def post_init(self, parent):
        self.parent = parent
        for member in dir(self):
            if member.startswith('__') and member.endswith('__'):
                continue
            if member == "parent":
                continue
            YmlObject.post_init_children(getattr(self, member), self)


class LazyEvaluator():
    def __init__(self, s):
        self.s = LazyStr(s)

    def update_context(self, update):
        self.s.update_context(update)

    def get(self):
        return eval(str(self.s))

    def __repr__(self):
        return f'{self.get()}'


class LazyStr(str):
    def update_context(self, update):
        if hasattr(self, "context"):
            self.context.update(update)
        else:
            self.context = update

    def __repr__(self):
        return str(self)

    def __str__(self):
        context = global_context
        if hasattr(self, "context"):
            context = {**context, **self.context}
        try:
            out = self.format(**context)
        except KeyError as e:
            close = difflib.get_close_matches(f'{e}', context)
            print(f'{e} parameter has no definition. closest match {close}')
            return self

        return out


class Action(YmlObject):
    supported_keys = [("name", None), ("parameters", {}), ("defaults", {})]

    def __init__(self, name="", defaults={}, parameters={}):
        super().__init__()
        self.name = name
        self.defaults = defaults
        self.parameters = parameters

    def run(self):
        return "N/A"

    def post_init(self, parent):
        # merge default, context and parameters
        parameters = self.defaults
        if parent:
            parameters = {**parameters, **parent.parameters}
        parameters = {**parameters, **self.parameters}
        # remove items that have been deleted
        parameters = {k: v for k, v in parameters.items() if v != None}
        self.parameters = parameters
        super().post_init(parent)


class Group(Action):
    supported_keys = [("name", None), ("list", None),
                      ("parameters", {}), ("defaults", {})]

    def __init__(self, name, list, defaults={}, parameters={}):
        super().__init__(name=name, defaults=defaults, parameters=parameters)
        self.list = list
        for test in self.list:
            if not isinstance(Test):
                raise Exception("Every element of the list must be a test")

    def run(self):
        for test in self.list:
            if isinstance(test, Group):
                print(f"===== Running group {test.name} ============")
                test.run()
            elif isinstance(test, Test):
                print(f"===== Running test {test.name} ============")
                test.run()


class LoaderError(Exception):
    pass

class Test(Action):
    supported_keys = [("name", None), ("sequence", None), ("setup", []),
                      ("teardown", []), ("parameters", {}), ("defaults", {}),
                      ("iterations", 1), ("continue_on_fail", False)]

    @staticmethod
    def from_yaml(filename, root=None):
        filename = str(filename)
        main = PathFinder.locate(filename, current_dir=root)
        if not main:
            raise LoaderError(f"Cannot locate {filename}")
        with open(main, 'r') as f:
            content = f.read()
        for append in PathFinder.locateall(filename + "_append", current_dir=root):
            with open(append, 'r') as f:
                content += '\n' + f.read()

        loader = YamlExtendedLoader(content, _path=main)
        try:
            r = loader.get_single_data()
            r._root = path.dirname(main)
        except LoaderError as e:
            print(f'Error in {main}: {e} ')
            r = None
        finally:
            loader.dispose()

        return r

    def __init__(self, name, sequence, defaults={}, parameters={}, setup=[], teardown=[], iterations=1, continue_on_fail=False):
        super().__init__(name=name, defaults=defaults, parameters=parameters)
        self.sequence = sequence
        self.setup = setup
        self.teardown = teardown
        self.iterations = iterations
        self.continue_on_fail = continue_on_fail

    def run(self):
        for a in self.setup:
            r = a.run()
            if r == "failed" and self.continue_on_fail:
                return "failed"
        for i in range(0, self.iterations):
            for a in self.sequence:
                r = a.run()
                if r == "failed" and not self.continue_on_fail:
                    return "failed"
        for a in self.teardown:
            a.run()
        return "Pass"

    def __repr__(self):
        return "(name=%r, defaults=%s, param=%s, seq=%s)" % (
            self.__class__.__name__, self.defaults, self.parameters, self.sequence)


class DeployFetch(Action):
    supported_keys = [("name", None), ("src", None), ("dst", None)]

    def __init__(self, name, is_deploy, src, dst):
        super().__init__(name = name)
        self.is_deploy = is_deploy
        self.src = src
        self.dst = dst

    def run(self):
        src = [s.format(**self.parent.parameters) for s in self.src]
        dst = self.dst.format(**self.parent.parameters)
        if self.is_deploy:
            print(f'deploy: {src} -> {dst}')
        else:
            print(f'fetch: {src} -> {dst}')
        return "N/A"

    def __repr__(self):
        return "(name=%r, deploy %s -> %s)" % (
            self.__class__.__name__, self.src, self.dst)


class Cmd(Action):
    supported_keys = [("name", None), ("cmd", None), ("defaults", {})]

    def __init__(self, cmd, name=None, defaults={}):
        super().__init__(name=name, defaults=defaults)
        self.cmd = cmd

    def __repr__(self):
        return "(name=%r, cmd=%s)" % (
            self.__class__.__name__, self.cmd)


class DutCmd(Cmd):
    def run(self):
        cmd = self.cmd
        print(f'DUT cmd: {cmd}')
        return "N/A"

    def __repr__(self):
        return "(name=%r, cmd=%s)" % (
            self.__class__.__name__, self.cmd)


class HostCmd(Cmd):
    def run(self):
        cmd = self.cmd
        print(f'HOST cmd: {cmd}')
        return "N/A"

    def __repr__(self):
        return "(name=%r, cmd=%s)" % (
            self.__class__.__name__, self.cmd)

class VariableSetter(Action):
    supported_keys = [("var", None), ("value", None)]

    def __init__(self, var, value):
        super().__init__(name = var)
        self.var = var
        self.value = value

    def run(self):
        var = str(self.var)
        value = eval(str(self.value))
        self.parent.update_params({var: value})
        print(f"SET {var} <- {self.parent.parameters[var]}")
        return "ignore"


class PythonTest(Test):
    supported_keys = [("name", None), ("module", None), ("test", None),
                      ("args", {}), ("parameters", {}), ("defaults", {})]

    def __init__(self, name, module, test, args, parameters, defaults):
        if not name:
            name = '.'.join([module,test])
        super().__init__(name=name, sequence = [], parameters=parameters, defaults=defaults)
        self.module = module
        self.test = test
        self.args = args

    def run(self):
        module = self.module
        test = self.test
        print(f'python test: {module}:{test}({self.args})')
        return "N/A"

    def __repr__(self):
        return "(name=%r, test=%s, params=%s)" % (
            self.__class__.__name__, self.test, self.args)

def construct_generic(loader, node: yaml.Node, cls, extras={}):
    fields = OverrideDict(loader.construct_mapping(node))
    params = {n: fields.get(n, default) for n, default in cls.supported_keys}

    supported_keys = [n for n, _ in cls.supported_keys]

    for f in fields:
        if not f in params:
            if '_' in f:
                g = '_'.join(f.split('_')[:-1])
                over = f.split('_')[-1]
            else:
                g = f
                over = None
            if not g in params:
                close = ['_'.join([s, over]) if over else s for s in difflib.get_close_matches(f'{f}', supported_keys)]
                print(f'Warning unused key "{f}" in {loader._path}. close matches {close}')

    obj = cls(**{**params, **extras})
    return obj


def construct_test(loader, node: yaml.Node):
    return construct_generic(loader, node, Test)


def construct_group(loader, node: yaml.Node):
    return construct_generic(loader, node, Group)


def construct_dut(loader, node: yaml.Node):
    if isinstance(node, yaml.ScalarNode):
        return DutCmd(loader.construct_scalar(node))
    return construct_generic(loader, node, DutCmd)


def construct_host(loader, node: yaml.Node):
    if isinstance(node, yaml.ScalarNode):
        return HostCmd(loader.construct_scalar(node))
    return construct_generic(loader, node, HostCmd)


def construct_python_test(loader, node: yaml.Node):
    return construct_generic(loader, node, PythonTest)


def construct_deploy(loader, node: yaml.Node):
    return construct_generic(loader, node, DeployFetch, {"is_deploy": True})


def construct_fetch(loader, node: yaml.Node):
    fields = OverrideDict(loader.construct_mapping(node))
    return construct_generic(loader, node, DeployFetch, {"is_deploy": False})


class YamlExtendedLoader(yaml.FullLoader):
    def __init__(self, content: str, _path: str):
        self._path = _path
        super().__init__(content)

    def construct_scalar(self, node):
        s = super().construct_scalar(node)
        if isinstance(s, str):
            if ((s.startswith('f"') and s.endswith('"')) or
                    (s.startswith("f'") and s.endswith("'"))):
                return LazyStr(s[2:-1])
            else:
                return s


def construct_from_yml(loader: YamlExtendedLoader, node: yaml.Node) -> Any:
    if isinstance(node, yaml.ScalarNode):
        return Test.from_yaml(node.value, root=path.dirname(loader._path))

    fields = OverrideDict(loader.construct_mapping(node))
    base_name = fields.get("path")
    params = fields.get("parameters", None)
    obj = Test.from_yaml(base_name, root=path.dirname(loader._path))
    if obj:
        if not obj.name:
            obj.name = base_name
        if params != None:
            obj.parameters = params
    return obj


def construct_from_eval(loader: YamlExtendedLoader, node: yaml.Node) -> Any:
    s = loader.construct_scalar(node)
    return LazyEvaluator(s)


def construct_set(loader: YamlExtendedLoader, node: yaml.Node) -> Any:
    fields = OverrideDict(loader.construct_mapping(node))
    var = fields.get("var")
    value = fields.get("value")
    return VariableSetter(var, value)


yaml.add_constructor('!group', construct_group, YamlExtendedLoader)
yaml.add_constructor('!test', construct_test, YamlExtendedLoader)
yaml.add_constructor('!dut', construct_dut, YamlExtendedLoader)
yaml.add_constructor('!host', construct_host, YamlExtendedLoader)
yaml.add_constructor('!deploy', construct_deploy, YamlExtendedLoader)
yaml.add_constructor('!fetch', construct_fetch, YamlExtendedLoader)
yaml.add_constructor('!python', construct_python_test, YamlExtendedLoader)
yaml.add_constructor('!yml', construct_from_yml, YamlExtendedLoader)
yaml.add_constructor('!eval', construct_from_eval, YamlExtendedLoader)
yaml.add_constructor('!set', construct_set, YamlExtendedLoader)

if __name__ == "__main__":
        #r = yaml.load(f.read(), Loader = YamlExtendedLoader)
    PathFinder.add(sys.argv[2])
    PathFinder.add(sys.argv[3])
    r = Test.from_yaml(sys.argv[1], "./")
    if r:
        r.post_init(None)
        # print(yaml.dump(r))
        r.run()

# Action :
    # does something.
    # return pass or fail

#!test:
    # derives from Action.
    # return log from the action
    # return metric
    # has parameters, a setup, a body (sequence) that can be iterated,  a teardown

#description (optionnal)
# setup (optionnal): list of actions not iterated executed before the sequence
# teardown(optionnal): list of actions not iterated executed after the sequence
# sequence: list of actions
# parameters (optionnal): dictionnary that will be used to adapt the actions
# defaults (optionnal): default paremeters

#!deploy: an action that transfers files from host to DUT
#!dut: shell cmd executed on the DUT
#!host: shell cmd executed on the host

#!python: python test executed on the host. the test must derive from TestBase. It takes parameters
