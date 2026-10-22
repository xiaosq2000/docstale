import assert from "node:assert/strict";
import childProcess from "node:child_process";
import {
	existsSync,
	mkdirSync,
	mkdtempSync,
	readFileSync,
	readdirSync,
	rmSync,
	writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { before, test, type TestContext } from "node:test";
import { createHarness } from "./harness.ts";

const executable =
	process.env.DOCSTALE_EXECUTABLE ||
	resolve(
		import.meta.dirname,
		"../..",
		".venv",
		process.platform === "win32" ? "Scripts/docstale.exe" : "bin/docstale",
	);

before(() => {
	assert.ok(
		existsSync(executable),
		"Run uv sync --all-groups before npm test, or set DOCSTALE_EXECUTABLE.",
	);
	process.env.DOCSTALE_EXECUTABLE = executable;
});

function fixture(t: TestContext) {
	const temporary = mkdtempSync(join(tmpdir(), "docstale-pi-"));
	const root = join(temporary, "checkout with spaces");
	mkdirSync(join(root, "src"), { recursive: true });
	t.after(() => rmSync(temporary, { recursive: true, force: true }));
	const git = (...args: string[]) =>
		childProcess
			.execFileSync("git", ["-C", root, ...args], { encoding: "utf8" })
			.trim();
	const cli = (...args: string[]) =>
		childProcess.spawnSync(executable, args, { cwd: root, encoding: "utf8" });
	const write = (path: string, contents: string) =>
		writeFileSync(join(root, path), contents);
	const stamp = () => assert.equal(cli("stamp", "README.md").status, 0);
	const commit = () => {
		git("add", "-A");
		git("commit", "-qm", "fixture");
	};
	git("init", "-q");
	git("config", "user.email", "docstale@example.invalid");
	git("config", "user.name", "Docstale Tests");
	write("src/app.py", "v1");
	write("README.md", "docs");
	write("docstale.toml", '[documents]\n"README.md" = ["src/"]\n');
	stamp();
	commit();
	const harness = createHarness(root);
	return { root, harness, git, cli, write, stamp, commit, temporary };
}

test("the package manifest exposes exactly the project extension", () => {
	const packageRoot = resolve(import.meta.dirname, "../..");
	const manifest = JSON.parse(
		readFileSync(join(packageRoot, "package.json"), "utf8"),
	);
	assert.deepEqual(manifest.pi.extensions, ["./.pi/extensions/docstale.ts"]);
	assert.ok(existsSync(resolve(packageRoot, manifest.pi.extensions[0])));
	assert.equal(manifest.dependencies, undefined);
	assert.equal(
		manifest.peerDependencies["@earendil-works/pi-coding-agent"],
		"*",
	);
});

test("the real hook ignores existing edits, reports new edits, and clears after stamp", async (t) => {
	const { harness, write, stamp, cli } = fixture(t);
	write("src/app.py", "existing edit");
	await harness.start();
	assert.equal(await harness.stop(), undefined);
	assert.equal(cli("check", "--json").status, 2);
	write("src/app.py", "session edit");
	const result = await harness.stop();
	assert.equal(result?.continue, true);
	assert.match(JSON.stringify(result?.entries), /README.md/);
	assert.match(JSON.stringify(result?.entries), /src\/app.py/);
	assert.match(JSON.stringify(result?.entries), /docstale stamp/);
	assert.equal(await harness.stop(), undefined);
	await harness.settled();
	assert.equal(await harness.stop(), undefined);
	stamp();
	assert.equal(await harness.stop(), undefined);
	assert.equal(cli("check", "--json").status, 0);
	write("src/app.py", "another edit");
	assert.equal((await harness.stop())?.continue, true);
});

test("resume, reload, compaction, and branch navigation preserve the baseline", async (t) => {
	const { harness, write, root, git } = fixture(t);
	await harness.start();
	const statePath = resolve(
		root,
		git("rev-parse", "--git-path", "docstale"),
		"baselines",
	);
	const baseline = join(statePath, readdirSync(statePath)[0]);
	const initial = readFileSync(baseline, "utf8");
	write("src/app.py", "session edit");
	await harness.start("resume");
	await harness.start("reload");
	await harness.emit("session_compact");
	await harness.emit("session_tree");
	assert.equal(readFileSync(baseline, "utf8"), initial);
	assert.equal((await harness.stop())?.continue, true);
});

test("new sessions and forks have independent baselines", async (t) => {
	const { harness, write } = fixture(t);
	await harness.start();
	write("src/app.py", "one's edit");
	harness.setSessionId("two");
	await harness.start("new");
	assert.equal(await harness.stop(), undefined);
	harness.setSessionId("fork");
	await harness.start("fork");
	assert.equal(await harness.stop(), undefined);
	harness.setSessionId("one");
	await harness.start("resume");
	assert.equal((await harness.stop())?.continue, true);
});

test("the real disable marker affects hooks but not manual commands", async (t) => {
	const { harness, cli, write, root, git } = fixture(t);
	assert.equal(cli("disable").status, 0);
	await harness.start();
	const statePath = resolve(root, git("rev-parse", "--git-path", "docstale"));
	assert.equal(existsSync(join(statePath, "baselines")), false);
	write("src/app.py", "disabled edit");
	assert.equal(await harness.stop(), undefined);
	assert.equal(cli("check", "--json").status, 2);
	assert.equal(cli("enable").status, 0);
	// With no baseline, the first check captures one silently.
	assert.equal(await harness.stop(), undefined);
	write("src/app.py", "enabled edit");
	assert.equal((await harness.stop())?.continue, true);
});

test("a missing executable warns at startup and requests one Stop continuation", async (t) => {
	const { harness, temporary } = fixture(t);
	const previous = process.env.DOCSTALE_EXECUTABLE;
	process.env.DOCSTALE_EXECUTABLE = join(temporary, "missing docstale");
	t.after(() => {
		if (previous === undefined) delete process.env.DOCSTALE_EXECUTABLE;
		else process.env.DOCSTALE_EXECUTABLE = previous;
	});
	await harness.start();
	assert.equal(harness.notifications.length, 1);
	assert.match(harness.notifications[0].message, /ENOENT/);
	const result = await harness.stop();
	assert.equal(result?.continue, true);
	assert.match(JSON.stringify(result), /ENOENT/);
	assert.equal(await harness.stop(), undefined);
});

test("a missing configuration stays silent", async (t) => {
	const { root, harness, write } = fixture(t);
	rmSync(join(root, "docstale.toml"));
	await harness.start();
	write("src/app.py", "edit");
	assert.equal(await harness.stop(), undefined);
	assert.deepEqual(harness.notifications, []);
});

test("a non-Git directory stays silent across requests", async (t) => {
	const root = mkdtempSync(join(tmpdir(), "docstale-pi-no-git-"));
	t.after(() => rmSync(root, { recursive: true, force: true }));
	const harness = createHarness(root);
	await harness.start();
	for (let request = 0; request < 3; request++) {
		assert.equal(await harness.stop(), undefined);
		await harness.settled();
	}
	// A configuration file does not make a directory a Git repository.
	writeFileSync(join(root, "docstale.toml"), "[broken");
	await harness.start("reload");
	assert.equal(await harness.stop(), undefined);
	assert.deepEqual(harness.notifications, []);
	assert.deepEqual(readdirSync(root), ["docstale.toml"]);
});

test("a broken configuration warns at startup and requests one Stop continuation", async (t) => {
	const { harness, write } = fixture(t);
	write("docstale.toml", "[broken");
	await harness.start();
	assert.equal(harness.notifications.length, 1);
	assert.match(
		harness.notifications[0].message,
		/docstale could not complete its check/,
	);
	assert.equal((await harness.stop())?.continue, true);
	assert.equal(await harness.stop(), undefined);
});

test("committing edits does not hide their impact", async (t) => {
	const { harness, write, commit } = fixture(t);
	await harness.start();
	write("src/app.py", "committed session edit");
	commit();
	assert.equal((await harness.stop())?.continue, true);
});

test("linked worktrees keep independent state for the same pi session ID", async (t) => {
	const { harness, git, temporary } = fixture(t);
	const linked = join(temporary, "linked checkout");
	git("worktree", "add", "-b", "linked", linked);
	const other = createHarness(linked);
	await harness.start();
	await other.start();
	writeFileSync(join(linked, "src/app.py"), "linked edit");
	assert.equal((await other.stop())?.continue, true);
	assert.equal(await harness.stop(), undefined);
	const primaryState = git("rev-parse", "--git-path", "docstale");
	const linkedState = childProcess
		.execFileSync(
			"git",
			["-C", linked, "rev-parse", "--git-path", "docstale"],
			{ encoding: "utf8" },
		)
		.trim();
	assert.notEqual(
		resolve(harness.ctx.cwd, primaryState),
		resolve(linked, linkedState),
	);
});

test("reverting an edit clears acknowledgement without changing the baseline", async (t) => {
	const { harness, write } = fixture(t);
	await harness.start();
	write("src/app.py", "v2");
	assert.equal((await harness.stop())?.continue, true);
	await harness.settled();
	write("src/app.py", "v1");
	assert.equal(await harness.stop(), undefined);
	write("src/app.py", "v2");
	assert.equal((await harness.stop())?.continue, true);
});
