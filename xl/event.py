# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3, or (at your option)
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.

# Provides a signals-like system for sending and listening for 'events'
#
#
# Events are kind of like signals, except they may be listened for on a 
# global scale, rather than connected on a per-object basis like signals 
# are. This means that ANY object can emit ANY event, and these events may 
# be listened for by ANY object. Events may be emitted either syncronously 
# or asyncronously, the default is asyncronous.
#
# The events module also provides an idle_add() function similar to that of
# gobject's. However this should not be used for long-running tasks as they
# may block other events queued via idle_add().
#
# Events should be emitted AFTER the given event has taken place. Often the
# most appropriate spot is immediately before a return statement.


import threading, time, logging
from xl import common

# define these here so the interperter doesn't complain about them
EVENT_MANAGER = None
IDLE_MANAGER  = None

logger = logging.getLogger(__name__)


def log_event(type, object, data, async=True):
    """
        Sends an event.

        type: the 'type' or 'name' of the event. [string]
        object: the object sending the event. [object]
        data: some data about the event. [object]
        async: whether or not to emit asyncronously. [bool]
    """
    global EVENT_MANAGER
    e = Event(type, object, data)
    if async:
        EVENT_MANAGER.emit_async(e)
    else:
        EVENT_MANAGER.emit(e)

def add_callback(function, type=None, object=None):
    """
        Sets an Event callback

        You should ALWAYS specify one of the two options on what to listen 
        for. While not forbidden to listen to all events, doing so will 
        cause your callback to be called very frequently, and possibly may 
        cause slowness within the player itself.

        @param function: the function to call when the event happens [function]
        @param type: the 'type' or 'name' of the event to listen for, eg 
                "track_added",  "cover_changed". Defaults to any event if 
                not specified. [string]
        @param object: the object to listen to events from, eg exaile.collection, 
                exaile.cover_manager. Defaults to any object if not 
                specified. [object]
    """
    global EVENT_MANAGER
    EVENT_MANAGER.add_callback(function, type, object)

def remove_callback(function, type=None, object=None):
    """
        Removes a callback

        The parameters passed should match those that were passed when adding
        the callback
    """
    EVENT_MANAGER.remove_callback(function, type, object)

def idle_add(func, *args):
    """
        Adds a function to run when there is spare processor time.
        
        func: the function to call [function]
        
        any additional arguments to idle_add will be passed on to the 
        called function.

        do not use for long-running tasks, so as to avoid blocking other
        functions.
    """
    global IDLE_MANAGER
    IDLE_MANAGER.add(func, *args)


class Event(object):
    """
        Represents an Event
    """
    def __init__(self, type, object, data):
        """
            type: the 'type' or 'name' for this Event [string]
            object: the object emitting the Event [object]
            data: some piece of data relevant to the Event [object]
        """
        self.type = type
        self.object = object
        self.data = data


class IdleManager(threading.Thread):
    """
        Simulates gobject's idle_add() using threads.
    """
    def __init__(self):
        threading.Thread.__init__(self)
        self.setDaemon(True)
        self.queue = []
        self.event = threading.Event()

        self.start()

    def run(self):
        """
            The main loop.
        """
        # This is quite simple. If we have a job, wake up and run it.
        # If we run out of jobs, sleep until we have another one to do.
        while True:
            if self.queue is None: return
            while len(self.queue) == 0:
                self.event.wait()
            self.event.clear()
            func, args = self.queue[0]
            self.queue = self.queue[1:]
            
            try:
                func.__call__(*args)
            except:
                common.log_exception(logger)

    def add(self, func, *args):
        """
            Adds a function to be executed.

            func: the function to execute [function]
            
            any additional arguments will be passed on to the called
            function
        """
        self.queue.append((func, args))
        self.event.set()


class EventManager(object):
    """
        Manages all Events
    """
    def __init__(self, use_logger=False):
        self.callbacks = {}
        self.idle = IdleManager()
        self.use_logger = use_logger

    def emit(self, event):
        """
            Emits an Event, calling any registered callbacks.

            event: the Event to emit [Event]
        """
        # find callbacks that match the Event
        callbacks = []
        for tcall in [None, event.type]:
            for ocall in [None, event.object]:
                try:
                    for call in self.callbacks[tcall][ocall]:
                        if call not in callbacks:
                            callbacks.append(call)
                except KeyError:
                    pass

        if self.use_logger:
            logger.debug("Sent '%s' event from '%s' with data '%s'."%(event.type, repr(event.object), repr(event.data)))

        # now call them
        for call in callbacks:
            try:
                call.__call__(event.type, event.object, event.data)
            except NameError:
                # the function we're trying to call disappeared
                self.remove_callback(call, event.type, event.object)
            except:
                # something went wrong inside the function we're calling
                common.log_exception(logger)

    def emit_async(self, event):
        """
            Same as emit(), but does not block.
        """
        self.idle.add(self.emit, event)

    def add_callback(self, function, type=None, object=None):
        """
            Registers a callback.
            You should always specify at least one of type or object.

            @param function: The function to call [function]
            @param type:     The 'type' or 'name' of event to listen for. Defaults
                to any. [string]
            @param object:   The object to listen to events from. Defaults
                to any. [string]
        """
        # add the specified categories if needed.
        if not self.callbacks.has_key(type):
            self.callbacks[type] = {}
        if not self.callbacks[type].has_key(object):
            self.callbacks[type][object] = []

        # add the actual callback
        self.callbacks[type][object].append(function)

    def remove_callback(self, function, type=None, object=None):
        """
            Unsets a callback. 

            The parameters must match those given when the callback was
            registered.
        """
        self.callbacks[type][object].remove(function)


class Waiter(threading.Thread):
    """
        This is kind of like the built-in python Timer class, except that
        it is possible to reset the countdown while the timer is running.
        It is intended for cases where we want to wait a certain interval
        of time after things stop changing before we do anything.

        Waiters can be used only once.
    """
    def __init__(self, interval, function, *args, **kwargs):
        threading.Thread.__init__(self)
        self.interval = interval
        self.function = function
        self.args = args
        self.kwargs = kwargs
        self.old_time = -1
        self.new_time = -1
        self.setDaemon(True)
        self.start()

    def reset(self):
        """
            Resets the timer
        """
        self.new_time = time.time()

    def run(self):
        self.old_time = time.time()
        while True:
            time.sleep(self.interval)
            if self.new_time > self.old_time + self.interval:
                self.interval = self.old_time + self.interval - \
                        self.new_time
                self.old_time = self.new_time
            else:
                break
        try:
            self.func.__call__(*self.args, **self.kwargs)
        except:
            common.log_exception(logger)

# Instantiate our managers as globals. This lets us use the same instance
# regardless of where this module is imported.
EVENT_MANAGER = EventManager()
IDLE_MANAGER  = IdleManager()

# vim: et sts=4 sw=4

