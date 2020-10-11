import os
import sys
from os import path
from typing import Any, IO
import yaml

context = {"board":"EVK", "overrides": ['evk', 'seb','imx8mm'], "DUT_IP":"192.168.1.29", "HOST_IP":"192.168.1.41", "mem_size":1992}

class Evaluator:
    def __init__(self, s):
        self.s = s

    def post_init(self, parent):
        self.parent = parent
        self.value = eval(self.s.format(**self.parent.parameters))

    def __repr__(self):
        return f'{self.value}'

class PathFinder():
    '''class holding the list of directories to be searched when looking for a file'''
    paths = []

    @staticmethod
    def add(path: str):
        PathFinder.paths.append(path)

    @staticmethod
    def locate(filename: str, current_dir: str = None) -> str:
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
        global context
        for ov in context["overrides"]:
            nk = name + '_' + ov
            if nk in self:
                return self[nk]
        return super().get(name, default)

class Action:
    def __init__(self):
        pass

    def post_init(self, parent):
        self.parent = parent

    def run(self):
        return "N/A"

class Test(Action):
    @staticmethod
    def from_yaml(context, filename, root = None):
        main = PathFinder.locate(filename, current_dir = root)
        with open(main, 'r') as f:
            content = f.read()
        for append in PathFinder.locateall(filename+"_append", current_dir = root):
            with open(append, 'r') as f:
                content += '\n' + f.read()
            
        loader = YamlExtendedLoader(content, _root=path.dirname(main))
        r = loader.get_single_data()
        loader.dispose()
        r._root = path.dirname(main)
        return r

    def __init__(self, name, context, sequence, defaults = {}, parameters = {}, setup = [] , teardown = []):
         self.name = name
         self.sequence = sequence
         self.defaults = defaults
         self.setup = setup
         self.teardown = teardown
         self.parameters = parameters
         self.context = context

    def post_init(self, parent):
        super().post_init(parent)

        # merge default, context and parameters
        parameters = {**self.defaults, **self.context}
        parameters = {**parameters, **self.parameters}
        # remove items that have been deleted
        parameters = { k: v for k,v in parameters.items() if v != None}

        # format the strings
        d = self.parent.parameters if self.parent else self.context
        for k,v in parameters.items():
                if isinstance(v,Evaluator):
                    parameters[k].post_init(self)
                if isinstance(v,str):
                    parameters[k] = v.format(**d)

        if "iterations" not in parameters:
            parameters["iterations"] = 1
        if "continue_on_fail" not in parameters:
            parameters["continue_on_fail"] = 1

        self.parameters = parameters

        for a in self.setup:
            a.post_init(self)
        for a in self.sequence:
            a.post_init(self)
        for a in self.teardown:
            a.post_init(self)


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
        cmd = self.cmd.format(**self.parent.parameters)
        print(f'DUT cmd: {cmd}')
        return "N/A"
    def __repr__(self):
        return "(name=%r, cmd=%s)" % (
            self.__class__.__name__, self.cmd)

class HostCmd(Cmd):
    def run(self):
        cmd = self.cmd.format(**self.parent.parameters)
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
        module = self.module.format(**self.parent.parameters)
        test = self.test.format(**self.parent.parameters)
        for k,v in self.args.items():
            if isinstance(v,str):
                args[k] = v.format(**self.parent.parameters)
            else:
                args[k] = v
        print(f'python test: {module}:{test}({args})')
        return "N/A"

    def __repr__(self):
        return "(name=%r, test=%s, params=%s)" % (
            self.__class__.__name__, self.test, self.args)

def get_field_overrides(dic, name, default = None, overrides = []):
    for ov in context["overrides"]:
        nk = name + '_' + ov
        if nk in dic:
            return dic[nk]
    return dic.get(name, default)

def construct_test(loader, node: yaml.Node):
    global context
    fields = OverrideDict(loader.construct_mapping(node))
    
    name  = fields.get("name")
    sequence = fields.get("sequence")
    setup = fields.get("setup", [])
    defaults = fields.get("defaults", {})
    parameters = fields.get("parameters", {})
    teardown = fields.get("teardown", [])

    return Test(name = name, context = context, sequence = sequence, setup = setup, teardown = teardown, parameters = parameters, defaults = defaults)

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
    obj = Test.from_yaml(context, base_name, root = loader._root)
    if params != None:
        obj.parameters = params
    return obj

def construct_from_eval(loader: YamlExtendedLoader, node: yaml.Node) -> Any:
    s = loader.construct_scalar(node)
    return Evaluator(s)

yaml.add_constructor('!test', construct_test, YamlExtendedLoader)
yaml.add_constructor('!dut', construct_dut, YamlExtendedLoader)
yaml.add_constructor('!host', construct_host, YamlExtendedLoader)
yaml.add_constructor('!deploy', construct_deploy, YamlExtendedLoader)
yaml.add_constructor('!fetch', construct_fetch, YamlExtendedLoader)
yaml.add_constructor('!python', construct_python_test, YamlExtendedLoader)
yaml.add_constructor('!remove', construct_none, YamlExtendedLoader)
yaml.add_constructor('!yml', construct_from_yml, YamlExtendedLoader)
yaml.add_constructor('!eval', construct_from_eval, YamlExtendedLoader)


    #r = yaml.load(f.read(), Loader = YamlExtendedLoader)
PathFinder.add(sys.argv[2])
PathFinder.add(sys.argv[3])
r = Test.from_yaml(context, sys.argv[1], "./")
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
