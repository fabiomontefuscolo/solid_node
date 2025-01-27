import os
import sys
import time
import inspect
import asyncio
import pyinotify
import traceback
from asyncio import Future
from importlib import import_module
from multiprocessing import Process
from subprocess import Popen
from solid_node.core import load_node


class Develop:
    """Monitor filesystem and executes transpilations and compilations on background"""

    def add_arguments(self, parser):
        parser.add_argument('-d', '--debug', action='store_true',
                            help='Debug mode supports breakpoints, but reload is not automatic')


    def openscad(self):
        from solid_node.viewers.openscad import OpenScadViewer
        OpenScadViewer(self.path).start()


    def monitor(self):
        task = Monitor(self.path, self.debug).run()
        loop = asyncio.get_event_loop()
        loop.run_until_complete(task)

    def handle(self, args):
        self.path = args.path
        self.debug = args.debug

        scad_proc = Process(target=self.openscad)
        scad_proc.start()

        if args.debug:
            return self.monitor()

        while True:
            p = Process(target=self.monitor)
            p.start()
            try:
                p.join()
            except KeyboardInterrupt:
                sys.exit(0)

        print(f"Exiting...")


class Monitor(pyinotify.ProcessEvent):
    """Monitors .py files and generate STLs, and exit on any change"""
    def __init__(self, path, debug):
        super().__init__()

        try:
            self.instance = load_node(path)
        except Exception as e:
            traceback.print_exc()
            self.instance = None

        self.debug = debug

        wm = pyinotify.WatchManager()
        loop = asyncio.get_event_loop()
        pyinotify.AsyncioNotifier(wm, loop, default_proc_fun=self)


        if self.instance:
            try:
                self.instance.assemble()
                print("Rendered!")
            except Exception as e:
                traceback.print_exc()

            mask = pyinotify.IN_CLOSE_WRITE

            for path in self.instance.files:
                print(f'watching {path}')
                wm.add_watch(path, mask)

        self.stl_task = None
        self.future = Future()

    async def run(self):
        self.stl_task = asyncio.create_task(self.generate_stl())
        await self.future

    async def generate_stl(self):
        try:
            self.instance.trigger_stl()
            self.stl_task = None
            print("All STLs built!")
        except StlRenderStart as job:
            sys.stdout.write(f"Building {job.stl_file}... ")
            sys.stdout.flush()
            while job.proc.poll() is None:
                await asyncio.sleep(0.2)
            job.finish()
            print("done, reloading")
            self.bye()
        except Exception as e:
            import traceback
            traceback.print_exc()

    def process_default(self, event):
        if not event.maskname == 'IN_CLOSE_WRITE':
            return
        print(f'{event.pathname} changed, reloading')
        self.bye()

    def bye(self):
        print('BYE!')
        self.future.set_result(None)
