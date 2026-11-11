// Validate the upload allowlist, Vercel schema and official Python entrypoint detector.
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '../..');
const tooling = path.join(root, 'temp/super_admin_validation/tooling/node_modules');
const ignore = require(path.join(tooling, 'ignore'));
const Ajv = require(path.join(tooling, 'ajv'));
const addFormats = require(path.join(tooling, 'ajv-formats'));
const {detectEntrypoint} = require(path.join(tooling, '@vercel/python'));
const minimatch = require(path.join(tooling, 'minimatch')).minimatch;

(async () => {
  const config = JSON.parse(fs.readFileSync(path.join(root, 'vercel.json')));
  const schema = JSON.parse(fs.readFileSync(path.join(root, 'temp/super_admin_validation/vercel.schema.json')));
  // The published schema labels draft-04 but contains modern numeric exclusiveMinimum.
  // Validate its property constraints using the matching draft-07 implementation.
  delete schema.$schema;
  const ajv = new Ajv({strict: false, allErrors: true, validateFormats: false});
  addFormats(ajv);
  const validate = ajv.compile(schema);
  assert.ok(validate(config), JSON.stringify(validate.errors));
  const rules = ignore().add(fs.readFileSync(path.join(root, '.vercelignore'), 'utf8'));
  const retained = [];
  function walk(directory, relative = '') {
    for (const entry of fs.readdirSync(directory, {withFileTypes: true})) {
      const name = relative + entry.name;
      if (entry.isDirectory()) {if (!rules.ignores(name + '/')) walk(path.join(directory, entry.name), name + '/');}
      else if (!rules.ignores(name)) retained.push(name);
    }
  }
  walk(root);
  const expected = ['.vercelignore', 'vercel.json', 'pyproject.toml',
    ...['__init__.py', 'app.py', 'models.py', 'security.py', 'settings.py', 'requirements.txt'].map(n => 'license_server/' + n),
    'licensing/__init__.py', 'licensing/protocol.py', 'super_admin/__init__.py',
    ...['__init__.py', 'app.py', 'routes.py', 'build_frontend.py'].map(n => 'super_admin/backend/' + n),
    ...['index.html', 'login.html', 'dashboard.js', 'login.js', 'style.css', 'network.js', 'three.module.min.js', 'THREE-LICENSE.txt'].map(n => 'super_admin/frontend/' + n)];
  assert.deepEqual(retained.sort(), expected.sort(), 'Unexpected file in Vercel upload allowlist');
  for (const file of ['data/pharmacy.db', 'database/sales_dao.py', 'backups/customer.db', 'temp/license_validation/pharmacy_clone.db', 'super_admin/backend/.env', 'super_admin/frontend/private.pem']) {
    assert.ok(rules.ignores(file), 'Sensitive file was not excluded: ' + file);
  }
  const exclusion = config.functions['super_admin/backend/app.py'].excludeFiles;
  for (const file of ['data/pharmacy.db', 'database/sales_dao.py', 'backups/customer.db', 'temp/license_validation/pharmacy_clone.db', 'pharmacy.db', 'private.pem', 'super_admin/backend/.env']) {
    assert.ok(minimatch(file, exclusion, {dot: true}), 'Sensitive file was not excluded from the function bundle: ' + file);
  }
  const entrypoint = await detectEntrypoint({workPath: root, framework: 'fastapi'});
  assert.equal(entrypoint?.entrypoint, 'super_admin.backend.app:app');
  const result = {schema_valid: true, official_builder_entrypoint: entrypoint, retained_files: retained, pharmacy_upload_excluded: true};
  fs.writeFileSync(path.join(root, 'temp/super_admin_validation/vercel_checks.json'), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
})().catch(error => {console.error(error); process.exitCode = 1;});
