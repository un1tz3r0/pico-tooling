import asyncio
import io
import os
import pathlib
import re
import shlex
import sys

import aiofiles

async def run(cmd, env={}):
		print(' '.join(["env",*[f"{str(k)}={str(v)}" for k,v in env.items()],*cmd]))
		proc = await asyncio.create_subprocess_exec("bash", "-c", " ".join([shlex.quote(word) for word in cmd]))
		return await proc.wait()

import contextlib

@contextlib.asynccontextmanager
async def withcwd(path):
		old = os.getcwd()
		path = pathlib.Path(path)
		if not path.is_absolute():
				path = pathlib.Path(__file__).parent / path
		pathlib.Path(path).mkdir(parents=True, exist_ok=True)
		os.chdir(path)
		try:
				yield
		finally:
				os.chdir(old)

import shlex

async def main(pico_path="pico", sdk_path="pico-sdk", dotenv_path=".env", no_apt=False, no_clone=False, no_extras=False, no_pull=False, no_picotool=False, sudo_prefix="sudo", git_prefix="git", apt_prefix="<sudo> apt"):
	if sudo_prefix == None:
		sudo_prefix = []
	else:
		if isinstance(sudo_prefix, str):
			sudo_prefix = [*shlex.split(sudo_prefix)]
		else:
			sudo_prefix = [*sudo_prefix]

	if pico_path == None:
		pico_path = "./pico"
	if isinstance(pico_path, str):
		pico_path = pathlib.Path(pico_path).absolute()

	if sdk_path == None:
		sdk_path = "pico-sdk"
	if isinstance(sdk_path, str):
		sdk_path = pico_path/sdk_path

	if git_prefix == None:
		git_prefix = []
	else:
		if isinstance(git_prefix, str):
			git_prefix = [*shlex.split(git_prefix)]
		else:
			git_prefix = [*git_prefix]

	# determine apt command parsed shell command prefix
	if apt_prefix == None:
		apt_prefix_words = ["$sudo_prefix", "apt", "-Y"]
	elif isinstance(apt_prefix, str):
		# parse shell cmd line into words, then subst each word if it starts with "$" from the following dict
		apt_prefix_kv={"sudo_prefix": sudo_prefix}
		apt_prefix_words=shlex.split(apt_prefix)
	else:
		apt_prefix_words=list([str(el) for el in apt_prefix])
	apt_prefix = list([(shlex.quote(word) if not word.startswith("$") else shlex.quote(apt_prefix_kv[word[1:]]) if word[1:] in apt_prefix_kv.keys() else '') for word in apt_prefix_words])

	# helper to run a git command in a subshell
	async def run_git(*args):
		print(f"Running git command: {' '.join([shlex.quote(word) for word in args])}")
		await run([*git_prefix, *args])

	# helper to run an apt command in a subshell
	async def run_apt(*args):
		print(f"Running apt command: {' '.join([shlex.quote(word) for word in args])}")
		await run([*sudo_prefix, *apt_prefix, *args])

	# helper to clone a missing folder from a git repo, or pull an existing folder's latest changes
	async def sync_git_repo(repo_url, branch=None, dir_name=None, parent_dir=None, submodules=False):
		if parent_dir == None:
			if dir_name != None and isinstance(dir_name, pathlib.Path):
				parent_dir = dir_name.parent
				dir_name = dir_name.name
			elif dir_name != None:
				parent_dir = pico_path/('/'.join('/'.split(dir_name)[:-1]))
				dir_name = '/'.split(dir_name)[-1]
			else:
				parent_dir = pico_path

		have_yarl = None
		try:
			import yarl
			have_yarl = True
		except ImportError as err:
			have_yarl = False
		
		if have_yarl:
			repo_url = yarl.URL(repo_url)
		else:
			pass
		
		if dir_name == None:
			if not have_yarl:
				dir_name = '/'.split('?'.split('#'.rsplit(str(repo_url),1)[0],1)[0])[-1]
			else:
				dir_name = repo_url.parts[-1]
			if dir_name.endswith(".git"):
				dir_name = dir_name[:-4]
		
		if isinstance(dir_name, pathlib.Path):
			dir_path = dir_name
		else:
			dir_path = pathlib.Path(parent_dir)/dir_name
		#assert(len(dir_name) > 0 and not dir_name.startswith("."))

		if not dir_path.exists():
			print(f"Cloning {f'branch {branch}' if branch != None else 'default branch'} of repo {repo_url} into dir {dir_name} in parent dir {parent_dir}...")
			async with withcwd(str(dir_path.parent.absolute())):
				await run_git("clone", *(["-b", branch] if branch != None else []), str(repo_url), str(dir_path.name))
				if not(not submodules):
					async with withcwd(str(dir_path.absolute())):
						await run_git("submodule", "update", "--init")
		else:
			print(f"Updating branch {branch} of repo {repo_url} in existing dir {dir_name} in parent dir {parent_dir}...")
			async with withcwd(str(dir_path.absolute())):
				await run_git("pull")

	# run apt commands unless no_apt=True
	if not no_apt:
		print("Running apt update & install packages...")
		await run([*sudo_prefix, "apt", "update", "-y"])
		await run([*sudo_prefix, "apt", "install", "-y", "git", "cmake", "gcc-arm-none-eabi", "gcc", "g++", "libstdc++-arm-none-eabi-newlib"])
		await run([*sudo_prefix, "apt", "install", "-y", "automake", "autoconf", "build-essential", "texinfo", "libtool", "libftdi-dev", "libusb-1.0-0-dev"])
	else:
		print("Skipping apt update & install packages...")

	# clone or update main sdk repo
	if not no_clone:
		print("Syncing main sdk repo...")
		await sync_git_repo("https://github.com/raspberrypi/pico-sdk.git", dir_name=sdk_path, submodules=True)
		await sync_git_repo("https://github.com/raspberrypi/picotool.git")
	else:
		print("Skipping sync of main sdk repo...")

	# clone or update extra repos
	if not no_clone and not no_extras:
		print("Syncing extra git repos...")
		await sync_git_repo("https://github.com/raspberrypi/pico-examples.git")
		await sync_git_repo("https://github.com/raspberrypi/pico-extras.git")
		await sync_git_repo("https://github.com/raspberrypi/pico-playground.git")
		await sync_git_repo("https://github.com/pimoroni/pico-boilerplate.git")
		await sync_git_repo("https://github.com/pimoroni/pimoroni-pico.git")
	else:
		print("Skipping sync of extra git repos...")

	if not no_picotool:
		print(f"Building picotool in {str(pico_path/'picotool')}...")
		async with withcwd(str(pico_path/"picotool")):
			await run(["cmake", "-B", "build", "-D", f"PICO_SDK_PATH={str(sdk_path.absolute())}"])
			await run(["make", "-C", "build"], env={"PICO_SDK_PATH": str(sdk_path.absolute())})
			print(f"Installing picotool from {str(pico_path/'picotool')}...")
			await run([*sudo_prefix, "make", "-C", "build", "install"], env={"PICO_SDK_PATH": str(sdk_path.absolute())})
	
	print("Writing environment dotfile...")
	async with aiofiles.open(str((pico_path/dotenv_path).absolute()), "wt") as f:
		await f.write(f"PICO_SDK_PATH={shlex.quote(str(sdk_path.absolute()))}\n")
		await f.write(f"PICO_EXAMPLES_PATH={shlex.quote(str((pico_path/'pico-examples').absolute()))}\n")
		await f.write(f"PICO_PLAYGROUND_PATH={shlex.quote(str((pico_path/'pico-playground').absolute()))}\n")
		await f.write(f"PICO_EXTRAS_PATH={shlex.quote(str((pico_path/'pico-extras').absolute()))}\n")
	print(f"Wrote env to dotfile:\n\t{dotenv_path}")

if __name__ == "__main__":
	asyncio.run(main())
