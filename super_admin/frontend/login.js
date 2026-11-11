document.querySelector('#login').addEventListener('submit', async event => {
  event.preventDefault();
  const button = event.target.querySelector('button');
  button.disabled = true;
  document.querySelector('#error').textContent = '';
  try {
    const response = await fetch('/admin/login', {method: 'POST', credentials: 'same-origin', signal: AbortSignal.timeout(15000), headers: {'Content-Type': 'application/json'}, body: JSON.stringify({username: document.querySelector('#username').value, password: document.querySelector('#password').value})});
    document.querySelector('#password').value = '';
    if (!response.ok) throw new Error(response.status === 429 ? 'Too many attempts. Try again later.' : 'Sign in failed. Check your credentials.');
    location.assign('/admin');
  } catch (error) { document.querySelector('#error').textContent = error.message; }
  finally { button.disabled = false; }
});
