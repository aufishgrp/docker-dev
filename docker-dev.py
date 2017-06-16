#!/usr/bin/python
import os
import os.path as osp
import sys
import argparse

def try_import(module, name):
	try:
		return __import__(module)
	except Exception:
		print "{name} is not installed. Run: sudo pip install {name} and try again.".format(name=name)
		sys.exit(-1)

yaml = try_import("yaml", "pyaml")
git  = try_import("git",  "gitpython")
apps = {}
services = {}

def make_path(path="", root="_build/apps"):
	return osp.join(root, path)

def apps_path():
	return make_path()

def app_path(app):
	return make_path(app)

def make_dir(path):
	if not osp.isdir(path):
		os.makedirs(path)
	return path

def parse_spec(spec):
	defaults = {"name": None,
	            "url":  None,
	            "ref":  "master"}
	if isinstance(spec, str):
		defaults.update({"url": spec})
	elif isinstance(spec, dict):
		defaults.update(spec)
	else:
		raise TypeError

	if defaults["name"] == None:
		defaults["name"] = osp.splitext(osp.basename(spec["url"]))[0]
	return defaults

def prep_repo(spec):
	global apps

	path = make_dir(app_path(spec["name"]))
	if not osp.isdir(osp.join(path, ".git")): ## If it hasn't been cloned
		repo = git.Repo.clone_from(spec["url"] if "url" in spec else spec, path)
	else: ## Make certain the correct checkout is pulled
		repo = git.Repo(path)
		remote = repo.remote("origin")
	
	repo.git.checkout(spec["ref"])
	#repo.git.clean("-dxf")
	apps[spec["name"]] = spec["ref"]
	return path

def prep_app(path):
	global apps
	try:
		app = osp.splitext(osp.basename(path))[0]
		with open(osp.join(path, "docker-dev.yml"), "r") as configfile: 
			configdata = yaml.load(configfile.read())
		
		if configdata["repos"] is None:
			return []

		paths = []
		for spec in configdata["repos"]:
			spec = parse_spec(spec)

			if spec["name"] in apps and apps[spec[name]] != spec["ref"]: ## If this app has been requested by another app and the versions differ
				raise Exceptions("Conflicting app versions {app}: {ver1} - {ver2}".format(name=spec["name"], ver1=apps[spec["name"]], ver2=[spec["ref"]]))
			elif spec["name"] in apps:
				pass ## Same version but seen again is a noop
			else:
				path = prep_repo(spec)
				if path is not None:
					paths.append(path)
		return paths
	except IOError:
		raise Exception("Dependency ({name}) is not docker-dev compatible".format(name=app))
		sys.exit(-1)

def prep():
	paths = ["."]
	for path in paths:
		newpaths = prep_app(path)
		paths += newpaths

def maybe_update_field(field, fun, path, data):
	if field in data:
		print "Update", field, data[field]
		data[field] = fun(path, data[field])	
	return data

def relpath(path):
	return osp.join(".", osp.relpath(osp.abspath(path), osp.join(os.getcwd(), "_build")))

def update_build_str(path, option):
	print "BUUILD", path, option, osp.join(path, option), relpath(osp.join(path, option))
	return osp.relpath(osp.abspath(path), osp.join(os.getdcwd(), ""))

def update_build_map(path, option):
	option["context"]    = relpath(osp.join(path, option["context"])) 
	option["dockerfile"] = option["dockerfile"] if "dockerfile" in option else "Dockerfile"
	return option

def update_build(path, option):
	if isinstance(option, str):
		return update_build_str(path, option)
	elif isinstance(option, dict):
		return update_build_map(path, option)

def update_envfile_str(path, option):
	return relpath(osp.join(path, option))

def update_envfile_list(path, option):
	return [update_envfile_str(path, x) for x in option]

def update_envfile(path, option):
	if isinstance(option, str):
		return update_envfile_str(path, option)
	elif isinstance(option, list):
		return update_envfile_list(path, option)

def update_volume_str(path, option):
	if option[0] == "~" or option == "/":
		return option
	elif option[0] != ".":
		return option
	else:
		tokens = option.split(":")
		tokens[0] = relpath(osp.join(path, tokens[0]))
		return ":".join(tokens)

def update_volume_map(path, option):
	option["source"] = update_volume_str(path, option["source"])
	return option

def update_volume(path, option):
	if isinstance(option, str):
		return update_volume_str(path, option)
	elif isinstance(option, dict):
		return update_volume_map(path, option)

def update_volumes(path, option):
	return [update_volume(path, x) for x in option]

def update_service(path, composedata):
	updates = [("build",    update_build),
	           ("env_file", update_envfile),
	           ("volumes",  update_volumes)]

	for (field, fun) in updates:
		composedata = maybe_update_field(field, fun, path, composedata)
	return composedata

def compose_dockercompose(app, path, composedata):
	with open(osp.join(path, "docker-compose.yml"), "r") as composefile:
		composesource = yaml.load(composefile.read())

	if "services" not in composesource:
		return composedata

	for service in composesource["services"]:
		if "services" not in composedata:
			composedata["services"] = {}

		servicedata = composesource["services"][service]
		if service in composedata["services"] and servicedata == composedata["services"][service]:
			continue
		elif service in composedata["services"]:
			raise Exception("Service {name} seen with differing definitions {def1} - {def2}".format(name=service, def1=composedata["services"][service], def2=servicedata))
		else:
			composedata["services"][service] = update_service(path, servicedata)
	return composedata

def compose():
	paths = [(x, osp.abspath(x)) for x in ["."] + [app_path(app) for app in apps]]
	composeoutput = {"version": "3.0"}

	for (app, path) in paths:
		try:
			if osp.isfile(osp.join(path, "docker-compose.yml")):
				composeoutput = compose_dockercompose(app, path, composeoutput)
			elif osp.isfile(osp.join(path, "Dockerfile")):
				composeoutput = compose_dockerfile(app, path, composeoutput)
		except IOError:
			continue

	with open("_build/docker-compose.yml", "w") as composefile:
		composefile.write(yaml.dump(composeoutput, default_flow_style=False))

if __name__ == "__main__":
	prep()
	compose()
	print "docker-compose -f _build/docker-compose.yml up"