/** Login em /admin/login */
(function () {
  function $(sel) { return document.querySelector(sel); }

  function applyAuthContext(ctx) {
    if (!ctx) return;
    var idField = ctx.identifier;
    if (idField) {
      $('#login-user-label').textContent = idField.label;
      if (idField.placeholder) $('#login-user').placeholder = idField.placeholder;
    }
    var passField = ctx.password;
    if (passField) {
      $('#login-pass-label').textContent = passField.label;
      if (passField.placeholder) $('#login-pass').placeholder = passField.placeholder;
    }
    var links = ctx.sigma_links;
    if (!links) return;
    var forgot = $('#link-recuperar-senha');
    var register = $('#link-cadastro');
    if (links.recuperar_senha && forgot) {
      forgot.href = links.recuperar_senha;
      forgot.hidden = false;
    }
    if (links.cadastro && register) {
      register.href = links.cadastro;
      register.hidden = false;
      $('#access-divider').hidden = false;
    }
  }

  function bindPasswordToggle() {
    var input = $('#login-pass');
    var btn = $('#login-toggle-pw');
    if (!input || !btn) return;
    btn.addEventListener('click', function () {
      var show = input.type === 'password';
      input.type = show ? 'text' : 'password';
      btn.setAttribute(
        'aria-label',
        show ? 'Ocultar senha' : 'Mostrar senha'
      );
    });
  }

  async function onLogin(ev) {
    ev.preventDefault();
    $('#login-error').hidden = true;
    var username = $('#login-user').value.trim();
    var password = $('#login-pass').value;
    var nextUrl = $('#login-next').value || '/admin/status';
    try {
      var res = await fetch('/admin/api/auth/login', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: username,
          password: password,
          next: nextUrl,
        }),
      });
      var data = {};
      try { data = await res.json(); } catch (_e) { /* ignore */ }
      if (!res.ok) {
        $('#login-error').hidden = false;
        if (res.status === 503) {
          $('#login-error').textContent =
            data.error || 'Servico de autenticacao indisponivel.';
        } else {
          $('#login-error').textContent =
            data.error || 'Usuario ou senha invalidos.';
        }
        return;
      }
      $('#login-pass').value = '';
      location.href = data.redirect || nextUrl;
    } catch (_err) {
      $('#login-error').hidden = false;
      $('#login-error').textContent =
        'Falha de comunicacao com o servidor.';
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    bindPasswordToggle();
    fetch('/admin/api/auth/context', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(applyAuthContext)
      .catch(function () {});
    $('#login-form').addEventListener('submit', onLogin);
  });
})();
