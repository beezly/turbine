// Finite, offline QA harness for templates/index.html's sendCommand().
// No browser, no server: extracts the function source via regex and runs
// it in a vm sandbox with mocked window/document/socket.
const fs = require('fs');
const vm = require('vm');

const html = fs.readFileSync('templates/index.html', 'utf8');
const m = html.match(/function sendCommand\(command\) \{[\s\S]*?\n        \}/);
if (!m) { console.error('FAIL: could not locate sendCommand()'); process.exit(1); }
const fnSrc = m[0];

function run(controlAvailable, confirmReturn) {
  const emits = [];
  const feedbacks = [];
  const state = { prompted: false };
  const sandbox = {
    window: {
      prompt: () => { state.prompted = true; return 'should-never-be-used'; },
      confirm: () => confirmReturn,
    },
    socket: { emit: (...args) => emits.push(args) },
    setFeedback: (kind, text) => feedbacks.push([kind, text]),
    console,
  };
  vm.createContext(sandbox);
  vm.runInContext(fnSrc + "\nthis.controlAvailable = " + controlAvailable + ";", sandbox);
  vm.runInContext('sendCommand("start")', sandbox);
  return { emits, feedbacks, state };
}

let failures = 0;
function check(label, cond) {
  if (!cond) { console.error('FAIL:', label); failures++; }
  else console.log('ok:', label);
}

// 1. Control unavailable -> never emits.
{
  const { emits, feedbacks } = run(false, true);
  check('control-disabled: no emit', emits.length === 0);
  check('control-disabled: error feedback', feedbacks.some(f => f[0] === 'err'));
}

// 2. User cancels confirm dialog -> nothing sent.
{
  const { emits } = run(true, false);
  check('confirm-cancelled: no emit', emits.length === 0);
}

// 3. User confirms -> emits dict {command} with no password field.
{
  const { emits, state } = run(true, true);
  check('confirmed: exactly one emit', emits.length === 1);
  const [event, payload] = emits[0] || [];
  check('confirmed: event name', event === 'command');
  check('confirmed: payload is dict', typeof payload === 'object' && payload !== null);
  check('confirmed: command field', payload && payload.command === 'start');
  check('confirmed: no password field', payload && !('password' in payload));
  check('confirmed: no window.prompt shown', state.prompted === false);
}

// 4. Source has no prompt, password handling, or storage.
check('source has no prompt()', !/prompt\(/.test(fnSrc));
check('source has no password variable', !/password/i.test(fnSrc.replace(/no control password configured/g, '')));
check('source has no localStorage', !/localStorage/.test(fnSrc));

console.log(failures === 0 ? '\nALL PASS' : `\n${failures} FAILURE(S)`);
process.exit(failures === 0 ? 0 : 1);
