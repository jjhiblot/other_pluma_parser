# Another parser that uses yaml tags to help construct the test objects.

This is really using yaml as an object serialization format.

All objects deriver from the Action class which basically offers a run() method

## TAGS

### !test

Is an action that executes other actions.

This is an action sequencer. It also provides the parameters to the underlying actions

### !python

Is an action that executes a python test on the host

### !yml

Is an action that executes a test described in another yml file

### !dut

Is an action that executes a shell command on the DUT

### !host

Is an action that executes a shell command on the HOST

### !deploy

Is an action that deploys files on the DUT

### !fetch

Is an action that fetch files from the DUT

### !eval
Is a way to call simple python function (main purpose is being able to call random.randint())
ex: 
    parameters:
        a_random_number: !eval random.randint(0,50)
        a_text: !eval "open('A FILE','r').read().strip()"
