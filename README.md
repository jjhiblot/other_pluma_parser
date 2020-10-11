# Another parser that uses yaml tags to help construct the test objects.

This is really using yaml as an object serialization format.

All objects deriver from the Action class which basically offers a run() method

## TAGS

### !test

Is an action that executes other actions.

This is an action sequencer. It also provides the parameters to the underlying actions
The basic structure is:

    !test
        # defaults: is a dictionnary of default values for the test parameters.
        # paremeters are 'variable' that can be used to parametize the test
        defaults:
             param_1: default_value_for_param1
             param_2: default_value_for_param2
             deploy_dir: /tmp/
             # iterations is a special parameter that is used internaly to repeat
             # the test's sequence. The value can a number of repetition or a minimum
             # duration
             iterations: 10

	# setup: is a list of actions to perform to set everything up before
        # the actual test. If one of them fail, the test is canceled
        setup:
	     - !deploy
		    src: [file://a_file, file://another_file]
                    dst: {deploy_dir}
        # sequence: is the body of the test.
        sequence:
             - !dut echo {param_1}
             - !dut cd {deploy_dir}
             - !dut diff -u a_file another_file
        # teardown: is called after the test is terminated. It is intended for cleanup
        teardown:
	     - !dut rm -rf {deploy_dir}/a_file {deploy_dir}/another_file}

### !yml

Is an action that executes a test described in another yml example:
The default values of the child test can be overloaded with the parameter dictionnary
example:

    !test
        defaults:
            this_test_param1: "bar"
        sequence:
            - !yml
                 path: path/to/another_test.yml
                 parameters:
                     child_param1: 45
                     child_param2: "foo {this_test_param1}"

### !dut

Is an action that executes a shell command on the DUT

### !host

Is an action that executes a shell command on the HOST

### !deploy

Is an action that deploys files on the DUT.
Parameters are:
- src: a list of URL to copy to the DUT
- dst: a directory or filename on the DUT
 
### !fetch

Is an action that fetch files from the DUT.
IT is basically the same as a !deploy command, except from the DUT to the host

### !python
Is an action that executes a python test on the host
example:

    !test
        defaults:
            this_test_param1: 500
        sequence:
            - !python 
                  module: testsuite.memory
                  test: MemorySize    
                  args:
                      total_mb: "{mem_size}"
                      available_mb: "{this_test_param1}"

Note: To make easier to substitute the parameters values in the python args, it is advised to
only use str parameters for the test. Using other types and substitution can be done using the
!eval constructor but make eveything more complicated

### !eval
Is a way to call simple python function (main purpose is being able to call random.randint())
ex: 

    parameters:
        a_random_number: !eval random.randint(0,50)
        a_file_content: !eval "open('A FILE','r').read().strip()"

## Classes

... TODO ...

## File lookup

In order to help with the customziation/overloading of tests, files
are not looked for in a single directory but in multiple locations,
let's call them test repositories.
To makes it really useful, all those test repo should have the same
organization.
example withe 2 test repos:

    main-test-corpus
     |_scripts
     |_tests
       |_network
       |_kernel
       |_crypto
       |_graphics

    project-specific-tests
     |_conf
     |_scripts
     |_tests
       |_kernel
       |_graphics

When a file 'subdir/a_file' is referenced in a yaml file a/b/c.yml, the parser
looks for a/b/subdir/a_file in all the test repos.

## Appending to YML file

To further help with the customization, when a yml file dir/a_test.yml is included (with the !yml constructor),
the parser will automatically append the content of all files matching dir/a_test.yml_append in the test repos.

    main-test-corpus
     |_tests
       |_graphics
        |_wayland-test.yml

    project-specific-tests
     |_tests
       |_graphics
         |_wayland-tests.yml_append

## Overrides

To make is easier to use different parameters for different configurations, the parameters and defaults
can be defined several times and selected based on 'tag'. This is similar to the concept of overrides
used by bitbake.
example:

    parameters:
        param1: "a generic value"
    parameters_board1:
        param1: "a value for the board 1"
    parameters_board1:
        param1: "a value for the board 1"
    parameters_imx8m:
        param1: "a value for imx8mm based boards"

The definition of the override tags a part of the configuration:
examples:

    system:
        overrides: ["board2", "project_name", "imx8mm", "imx8", "aarch64"]
