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
            #print(f"Found {filename}")
            return filename
        l = [current_dir] if current_dir else []
        if PathFinder.paths:
            l.extend(PathFinder.paths)
        for d in l:
            p = path.join(d, filename)
            if path.exists(p):
                #print(f"Found {p}")
                return p
        #print(f"Did not find {p}")
        return None

    @staticmethod
    def locateall(filename: str, current_dir: str = None) -> str:
        filename = str(filename)
        result = []
        if path.isabs(filename):
            #print(f"Found {[filename]}")
            return [filename]
        l = [current_dir] if current_dir else []
        if PathFinder.paths:
            l.extend(PathFinder.paths)
        for d in l:
            p = path.join(d, filename)
            if path.exists(p):
                result.append(p)
        #print(f"Found {result}")
        return result

class OverrideDict(dict):
    def get(self, name, default = None):
        global global_context
        for ov in global_context["overrides"]:
            nk = name + '_' + ov
            if nk in self:
                return self[nk]
        return super().get(name, default)


class LazyStr():
    def __init__(self, s, parent = None):
        self.fmt = s
        self.parent = parent

    def __str__(self):
        context = global_context
        if hasattr(self.parent, "parameters"):
            if self.parent.parameters:
                    context = {**context, **self.parent.parameters}
        out = self.fmt.format(**context)
        if (out != self.fmt):
            print(f'{self.fmt} -> {out}')
        return out

def expand_str(obj, parent):
    if isinstance(obj, dict):
        for k in obj:
             return { k:expand_str(v, parent) for (k,v ) in obj.items() }
    elif isinstance(obj, list):
        return [ expand_str(e, parent) for e in obj]
    elif isinstance(obj, LazyStr):
        obj.parent = parent
        return obj
    else:
        return obj


class YmlObject:
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

    def post_init(self, parent):
        global global_context
        context = global_context

        if hasattr(parent, "parameters"):
            if parent.parameters:
                context = {**context, **parent.parameters}
                    
        for member in dir(self):
            if member.startswith('__') and member.endswith('__'):
                continue
            child = getattr(self, member)
            #setattr(self, member, expand_str(child, parent))

        for member in dir(self):
            if member.startswith('__') and member.endswith('__'):
                continue
            if member == "parent":
                continue
            child = getattr(self, member)
            YmlObject.post_init_children(child, self)


        self.parent = parent

class Evaluator(YmlObject):
    def __init__(self, s):
        self.s = s

    def get(self):
        return eval(self.s.format({**global_context, **self.parent.parameters}))

    def post_init(self, parent):
        self.parent = parent

    def __repr__(self):        
        return f'{self.get()}'

class Action(YmlObject):
    def run(self):
        return "N/A"

class Test(Action):
    @staticmethod
    def from_yaml(context, filename, root = None):
        filename = str(filename)
        main = PathFinder.locate(filename, current_dir = root)
        with open(main, 'r') as f:
            content = f.read()
        for append in PathFinder.locateall(filename + "_append", current_dir = root):
            with open(append, 'r') as f:
                content += '\n' + f.read()
 
        loader = YamlExtendedLoader(content, _root=path.dirname(main))
        r = loader.get_single_data()
        loader.dispose()
        r._root = path.dirname(main)
        return r

    def __init__(self, name, sequence, defaults = {}, parameters = {}, setup = [] , teardown = []):
         self.name = name
         self.sequence = sequence
         self.defaults = defaults
         self.setup = setup
         self.teardown = teardown
         self.parameters = parameters

    def post_init(self, parent):
        self.parent = parent

        # merge default, context and parameters
        parameters = {**self.defaults, **self.parameters}
        # remove items that have been deleted
        parameters = { k: v for k,v in parameters.items() if v != None}

        if "iterations" not in parameters:
            parameters["iterations"] = 1
        if "continue_on_fail" not in parameters:
            parameters["continue_on_fail"] = 1

        self.parameters = parameters
        super().post_init(parent)


    def run(self):
        for a in self.setup:
            r = a.run()
            if r == "failed" and not self.parameters.continue_on_fail:
                return "failed"
        for i in range(0, self.parameters["iterations"]):
            for a in self.sequence:
                r = a.run()
                if r == "failed" and not self.parameters.continue_on_fail:
                    return "failed"
        for a in self.teardown:
            a.run()
        return "Pass"    

    def __repr__(self):
         return "(name=%r, defaults=%s, param=%s, seq=%s)" % (
             self.__class__.__name__, self.defaults, self.parameters, self.sequence)

class DeployFetch(Action):
    def __init__(self, is_deploy, src, dst):
        self.is_deploy = is_deploy
        self.src = src
        self.dst = dst

    def run(self):
        src = [ s.format(**self.parent.parameters) for s in self.src]
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
     def __init__(self, cmd):
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

class PythonTest(Action):
    def __init__(self, module, test, args):
        self.module = module
        self.test = test
        self.args = args

    def run(self):
        args = {}
        module = self.module
        test = self.test
        print(f'python test: {module}:{test}({args})')
        return "N/A"

    def __repr__(self):
        return "(name=%r, test=%s, params=%s)" % (
            self.__class__.__name__, self.test, self.args)

def get_field_overrides(dic, name, default = None, overrides = []):
    for ov in global_context["overrides"]:
        nk = name + '_' + ov
        if nk in dic:
            return dic[nk]
    return dic.get(name, default)

def construct_test(loader, node: yaml.Node):
    global global_context
    fields = OverrideDict(loader.construct_mapping(node))
    
    name  = fields.get("name")
    sequence = fields.get("sequence")
    setup = fields.get("setup", [])
    defaults = fields.get("defaults", {})
    parameters = fields.get("parameters", {})
    teardown = fields.get("teardown", [])

    return Test(name = name, sequence = sequence, setup = setup, teardown = teardown, parameters = parameters, defaults = defaults)

def construct_dut(loader, node: yaml.Node):
    return DutCmd(loader.construct_scalar(node))

def construct_host(loader, node: yaml.Node):
    return HostCmd(loader.construct_scalar(node))

def construct_python_test(loader, node: yaml.Node):
    fields = OverrideDict(loader.construct_mapping(node))
    return PythonTest(fields.get("module"), fields.get("test"), fields.get("args"))

def construct_deploy(loader, node: yaml.Node):
    fields = OverrideDict(loader.construct_mapping(node))
    return DeployFetch(is_deploy=True, src = fields.get("src"), dst = fields.get("dst"))

def construct_fetch(loader, node: yaml.Node):
    fields = OverrideDict(loader.construct_mapping(node))
    return DeployFetch(is_deploy=False, src = fields.get("src"), dst = fields.get("dst"))

def construct_none(loader, node: yaml.Node):
    return None

class YamlExtendedLoader(yaml.FullLoader):
    def __init__(self, content: str, _root: str):
        self._root = _root
        super().__init__(content)

#class PathFinder:
    #def locate(current_dir, filename):
        #return filename
    #def locateall(current_dir, filename):
        #return []

def construct_from_yml(loader: YamlExtendedLoader, node: yaml.Node) -> Any:
    fields = OverrideDict(loader.construct_mapping(node))
    base_name = fields.get("path")
    params = fields.get("parameters", None)
    obj = Test.from_yaml(global_context, base_name, root = loader._root)
    if params != None:
        obj.parameters = params
    return obj

def construct_from_eval(loader: YamlExtendedLoader, node: yaml.Node) -> Any:
    s = loader.construct_scalar(node)
    return Evaluator(s)

class VariableSetter(Action):
    def __init__(self, var, value):
        self.var = var
        self.value = value

    def run(self):
        var = f'{self.var}'
        value = eval(f'{self.value}')
        self.parent.parameters[var] = eval(f'{self.value}')
        print(f"SET {var} {self.parent.parameters[var]}")
        return "ignore"

def construct_set(loader: YamlExtendedLoader, node: yaml.Node) -> Any:
    fields = OverrideDict(loader.construct_mapping(node))
    var = fields.get("var")
    value = fields.get("value")
    return VariableSetter(var, value)

def construct_lazy_str(loader: YamlExtendedLoader, node: yaml.Node) -> Any:
    return LazyStr(loader.construct_scalar(node))

def construct_mapping(self, node, deep=False):
    if not isinstance(node, yaml.MappingNode):
        raise ConstructorError(None, None,
                "expected a mapping node, but found %s" % node.id,
                node.start_mark)
    mapping = {}
    for key_node, value_node in node.value:
        key = self.construct_object(key_node, deep=deep)
        if not isinstance(key, Hashable):
            raise ConstructorError("while constructing a mapping", node.start_mark,
                    "found unhashable key", key_node.start_mark)
        value = self.construct_object(value_node, deep=deep)
        mapping[f'{key}'] = value
    return mapping

YamlExtendedLoader.construct_mapping = construct_mapping

yaml.add_constructor('!test', construct_test, YamlExtendedLoader)
yaml.add_constructor('!dut', construct_dut, YamlExtendedLoader)
yaml.add_constructor('!host', construct_host, YamlExtendedLoader)
yaml.add_constructor('!deploy', construct_deploy, YamlExtendedLoader)
yaml.add_constructor('!fetch', construct_fetch, YamlExtendedLoader)
yaml.add_constructor('!python', construct_python_test, YamlExtendedLoader)
yaml.add_constructor('!remove', construct_none, YamlExtendedLoader)
yaml.add_constructor('!yml', construct_from_yml, YamlExtendedLoader)
yaml.add_constructor('!eval', construct_from_eval, YamlExtendedLoader)
yaml.add_constructor('!set', construct_set, YamlExtendedLoader)
yaml.add_constructor('tag:yaml.org,2002:str',construct_lazy_str, YamlExtendedLoader)

if __name__ == "__main__":
        #r = yaml.load(f.read(), Loader = YamlExtendedLoader)
    PathFinder.add(sys.argv[2])
    PathFinder.add(sys.argv[3])
    r = Test.from_yaml(global_context, sys.argv[1], "./")
    r.post_init(None)

    #print(yaml.dump(r))
    r.run()

#Action :
    #does something.
    #return pass or fail

#!test:
    #derives from Action.
    #return log from the action
    #return metric
    #has parameters, a setup, a body (sequence) that can be iterated,  a teardown

#description (optionnal)
#setup (optionnal): list of actions not iterated executed before the sequence
#teardown(optionnal): list of actions not iterated executed after the sequence
#sequence: list of actions
#parameters (optionnal): dictionnary that will be used to adapt the actions
#defaults (optionnal): default paremeters

#!deploy: an action that transfers files from host to DUT
#!dut: shell cmd executed on the DUT
#!host: shell cmd executed on the host

#!python: python test executed on the host. the test must derive from TestBase. It takes parameters
