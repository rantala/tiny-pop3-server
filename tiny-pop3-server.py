#!/usr/bin/python
# Small POP3 server with GUI for development purposes.
#
# Dependencies:
# - python
# - twisted (python package)
# - zope.interface (python package)
#
# Copyright (c) 2013 Tommi Rantala <tt.rantala@gmail.com>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import tkinter as T
from tkinter import filedialog
import hashlib
from io import StringIO

import twisted.mail.pop3
from twisted.internet import tksupport, reactor
from twisted.cred.portal import Portal, IRealm
from twisted.internet.protocol import ServerFactory
from twisted.mail.pop3 import IMailbox
from twisted.cred.checkers import InMemoryUsernamePasswordDatabaseDontUse
from zope.interface import implementer

DEFAULT_USERNAME = 'user'
DEFAULT_PASSWORD = 'pass'

EVENT_MAILBOXCHANGE = '<<mailboxchange>>'
EVENT_MESSAGELOGCHANGE = '<<messagelogchange>>'

root = None
messagelog = []


class Service:
	def __init__(self):
		self.port = 12340
		self.interface = '127.0.0.1'
		self.listeningPort = None
		self.username = DEFAULT_USERNAME
		self.password = DEFAULT_PASSWORD


def emit_event(event):
	# print(f"Emitting event {event}")
	root.event_generate(event, when='tail')


def incoming_line(line):
	messagelog.append("C: " + line.decode().strip("\n\r"))
	emit_event(EVENT_MESSAGELOGCHANGE)


def outgoing_line(line):
	messagelog.append("S: " + line.decode().strip("\n\r"))
	emit_event(EVENT_MESSAGELOGCHANGE)


# Use a class for each message we store in the mailbox.
class Message:
	def __init__(self, content=None, label=None):
		self.__content = content
		self.__label = label
		self.__deleted = False

	def content(self):
		return self.__content

	def label(self):
		label = None
		if self.__label:
			label = '' + self.__label
		if self.deleted() and label:
			label = label + ' (deleted)'
		return label

	def deleted(self):
		return self.__deleted

	def delete(self):
		self.__deleted = True

	def undelete(self):
		self.__deleted = False


@implementer(IMailbox)
class Mailbox:
	def __init__(self):
		self.messages = []

	def listMessages(self, index=None):
		if index is None:
			return [len(m.content()) for m in self.messages]
		if index >= len(self.messages):
			raise ValueError
		return len(self.messages[index].content())

	def getMessage(self, index):
		if index >= len(self.messages):
			raise ValueError
		return StringIO.StringIO(self.messages[index].content())

	def getUidl(self, index):
		if index >= len(self.messages):
			raise ValueError
		return hashlib.sha1(self.messages[index].content()).hexdigest()

	def deleteMessage(self, index):
		if index >= len(self.messages):
			raise ValueError
		self.messages[index].delete()
		emit_event(EVENT_MAILBOXCHANGE)

	def undeleteMessages(self, index):
		if index >= len(self.messages):
			raise ValueError
		self.messages[index].undelete()
		emit_event(EVENT_MAILBOXCHANGE)

	def sync(self):
		keep = []
		for message in self.messages:
			if not message.deleted():
				keep.append(message)
		self.messages = keep
		emit_event(EVENT_MAILBOXCHANGE)

	def addMessage(self, msg):
		self.messages.append(msg)
		emit_event(EVENT_MAILBOXCHANGE)


@implementer(IRealm)
class SimpleRealm:
	def __init__(self, mailbox):
		self.mailbox = mailbox

	def requestAvatar(self, avatarId, mind, *interfaces):
		if IMailbox not in interfaces:
			raise NotImplementedError()
		return IMailbox, mailbox, lambda: None


# I want to log all traffic between the client and the server. Use our own
# server class to get the most interesting events from the twisted framework.
class POP3Server(twisted.mail.pop3.POP3):

	# Could show something in the UI to indicate a connected client:
	# def connectionMade(self):
	# twisted.mail.pop3.POP3.connectionMade(self)

	def successResponse(self, message=''):
		outgoing_line(twisted.mail.pop3.successResponse(message))
		twisted.mail.pop3.POP3.successResponse(self, message)

	def lineReceived(self, line):
		incoming_line(line)
		twisted.mail.pop3.POP3.lineReceived(self, line)

	def sendLine(self, line):
		outgoing_line(line)
		twisted.mail.pop3.POP3.sendLine(self, line)


class GUI:
	class HScrollList(T.Frame):
		def __init__(self, master):
			T.Frame.__init__(self, master)
			self.list = T.Listbox(self)
			self.list.pack(side=T.LEFT, expand=T.YES, fill=T.BOTH)
			self.scrollbar = T.Scrollbar(self, command=self.list.yview)
			self.list['yscrollcommand'] = self.scrollbar.set
			self.scrollbar.pack(side=T.LEFT, fill=T.BOTH)

	class HScrollText(T.Frame):
		def __init__(self, master):
			T.Frame.__init__(self, master)
			self.text = T.Text(self)
			self.text.pack(side=T.LEFT, expand=T.YES, fill=T.BOTH)
			self.scrollbar = T.Scrollbar(self, command=self.text.yview)
			self.text['yscrollcommand'] = self.scrollbar.set
			self.scrollbar.pack(side=T.LEFT, fill=T.BOTH)

	def __init__(self, master, mailbox, service):
		self.master = master
		self.mailbox = mailbox
		self.service = service
		self.message_generate_count = 0

		master.title("POP3 Server {}:{}".format(service.interface, service.port))

		topframe = T.Frame(master)
		topframe.pack(expand=T.YES, fill=T.BOTH)

		message_frame = T.Frame(topframe)
		message_frame.pack(side=T.TOP, expand=T.YES, fill=T.BOTH)

		message_list_frame = T.Frame(message_frame)
		message_list_frame.pack(side=T.LEFT, expand=T.YES, fill=T.BOTH)

		T.Label(message_list_frame, text='Messages:').pack(side=T.TOP, fill=T.X)

		self.message_list = GUI.HScrollList(message_list_frame)
		self.message_list.pack(expand=T.YES, fill=T.BOTH)
		self.message_list.list.bind('<Button-1>', self.display_message)
		master.bind(EVENT_MAILBOXCHANGE, self.refresh_message_list)

		self.add_message_button = T.Button(message_list_frame, text='Add Test Message', command=self.add_message)
		self.add_message_button.pack(side=T.TOP, fill=T.X)

		self.import_message_button = T.Button(message_list_frame, text='Import Message from File', command=self.import_message)
		self.import_message_button.pack(side=T.TOP, fill=T.X)

		message_content_frame = T.Frame(message_frame)
		message_content_frame.pack(side=T.LEFT, expand=T.YES, fill=T.BOTH)
		T.Label(message_content_frame, text='Message content:').pack(fill=T.X)
		self.messagecontent = GUI.HScrollText(message_content_frame)
		self.messagecontent.pack(expand=T.YES, fill=T.BOTH)

		message_log_frame = T.Frame(topframe)
		message_log_frame.pack(side=T.TOP, expand=T.YES, fill=T.BOTH)
		T.Label(message_log_frame, text='Protocol message log:').pack(fill=T.X)
		self.message_log_content = GUI.HScrollText(message_log_frame)
		self.message_log_content.pack(expand=T.YES, fill=T.BOTH)
		master.bind(EVENT_MESSAGELOGCHANGE, self.refresh_message_log_content)

	def add_message(self):
		self.message_generate_count += 1
		m = Message(f"Hi there!\nGenerated message number {self.message_generate_count} goes here.\n")
		self.mailbox.addMessage(m)

	def import_message(self):
		filenames = filedialog.askopenfilenames()
		if not filenames:
			return

		# http://bugs.python.org/issue5712
		filenames = self.master.tk.splitlist(filenames)
		print(f"Importing files: {filenames}")

		for filename in filenames:
			print(f"Opening file '{filename}'")
			f = open(filename)
			content = f.read()
			f.close()
			# print(f"MESSAGE: {content}")
			self.mailbox.addMessage(Message(content, f.name))

	def refresh_message_list(self, event=None):
		self.message_list.list.delete(0, T.END)
		for idx in range(1, len(self.mailbox.messages) + 1):
			if self.mailbox.messages[idx - 1].label():
				label = f"Message {idx}: {self.mailbox.messages[idx - 1].label()}"
			else:
				label = f"Message {idx}"
			self.message_list.list.insert(T.END, label)

	def refresh_message_log_content(self, event=None):
		self.message_log_content.text.delete('0.0', T.END)
		for message in messagelog:
			self.message_log_content.text.insert(T.END, message)
			self.message_log_content.text.insert(T.END, "\n")

	def display_message(self, event):
		if len(self.mailbox.messages) == 0:
			return
		message_num = self.message_list.list.nearest(event.y)
		self.messagecontent.text.delete('0.0', T.END)
		self.messagecontent.text.insert('0.0', self.mailbox.messages[message_num].content())


if __name__ == '__main__':
	service = Service()
	mailbox = Mailbox()
	portal = Portal(SimpleRealm(mailbox))
	auth = InMemoryUsernamePasswordDatabaseDontUse()
	auth.addUser(service.username, service.password)
	portal.registerChecker(auth)

	f = ServerFactory()
	f.protocol = POP3Server
	f.protocol.portal = portal

	print(f"Starting to listen on {service.interface}:{service.port}...")
	service.listeningPort = reactor.listenTCP(port=service.port, factory=f, interface=service.interface)
	# root.addCleanup(service.listeningPort.stopListening)

	root = T.Tk()
	tksupport.install(root)
	root.protocol('WM_DELETE_WINDOW', reactor.stop)
	gui = GUI(root, mailbox, service)

	print("Entering event loop!")
	reactor.run()
