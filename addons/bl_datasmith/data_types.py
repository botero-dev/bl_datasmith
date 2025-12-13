# SPDX-FileCopyrightText: 2018-2025 Andrés Botero
# SPDX-License-Identifier: AGPL-3.0-only
# SPDX-FileName: data_types.py

invalid_chars = [
	" ",  # ue4 doesn't like spaces in filenames, better just reject them everywhere
	".",
	",",
	"/",
	"?",
	"<",
	">",
	";",
	":",
	"'",
	'"',
	"~",
	"`",
	"[",
	"]",
	"{",
	"}",
	"\\",
	"|",
	"!",
	"@",
	"#",
	"$",
	"%",
	"^",
	"&",
	"*",
	"(",
	")",
	"=",
]


def sanitize_name(name):
	output = name
	for invalid_char in invalid_chars:
		if invalid_char in name:
			output = output.replace(invalid_char, "_")

	if output[0] == "_":
		# unreal doesn't like when names start in underscore
		output = "0%s" % output
	return output


class Node:
	prefix = ""

	def __init__(self, name, attrs=None, children=None):
		self.name = name
		self.children = children or []
		if attrs:
			assert type(attrs) is dict
		self.attrs = attrs or {}

	def __getitem__(self, key):
		return self.attrs[key]

	def __setitem__(self, key, value):
		self.attrs[key] = value

	def string_rep(self, first=False):
		previous_prefix = Node.prefix
		if first:
			Node.prefix = ""
		else:
			Node.prefix += "\t"
		output = Node.prefix + "<{}".format(self.name)
		if first:
			Node.prefix = "\n"
		for attr in self.attrs:
			output += ' {key}="{value}"'.format(key=attr, value=self.attrs[attr])

		if self.children:
			output += ">"
			for child in self.children:
				output += str(child)
			if len(self.children) == 1 and type(self.children[0]) is str:
				# TODO: instead of doing this, I think it would be nice to allow children
				# to be a string, because that is when we're interested in inlining
				output += "</{}>".format(self.name)
			else:
				output += Node.prefix + "</{}>".format(self.name)
		else:
			output += "/>"
		Node.prefix = previous_prefix
		return output

	def __str__(self):
		return self.string_rep()

	def push(self, value):
		size = len(self.children)
		self.children.append(value)
		return size
