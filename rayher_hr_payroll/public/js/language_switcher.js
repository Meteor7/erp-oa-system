frappe.provide('rayher.i18n');

// Languages offered by the switcher. Only fully-translated locales are listed;
// French (fr) stays out until locale/fr.po is complete (backend i18n.py still
// accepts it). Keep in sync with rayher_hr_payroll/i18n.py: SUPPORTED_LANGUAGES.
rayher.i18n.LANGUAGES = [
	{ value: 'en', label: 'English' },
	{ value: 'zh', label: '中文' },
];

rayher.i18n.set_language = function (language) {
	if (language === frappe.boot.lang) {
		return;
	}
	frappe
		.xcall('rayher_hr_payroll.i18n.set_language', { language })
		.then((result) => {
			if (result && result.reload) {
				window.location.reload();
			}
		});
};

rayher.i18n.render_switcher = function () {
	const $navbar = $('header.navbar .navbar-nav').last();
	if (!$navbar.length || $navbar.find('.rayher-language-switcher').length) {
		return !!$navbar.length;
	}

	const current = frappe.boot.lang || 'en';
	const current_label = (
		rayher.i18n.LANGUAGES.find((l) => l.value === current) || { label: current }
	).label;

	const items = rayher.i18n.LANGUAGES.map((l) => {
		const active = l.value === current ? ' active' : '';
		return `<li><a class="dropdown-item${active}" data-lang="${l.value}" href="#">${frappe.utils.escape_html(
			l.label
		)}</a></li>`;
	}).join('');

	const $li = $(`
		<li class="nav-item dropdown rayher-language-switcher" title="${frappe.utils.escape_html(__('Language'))}">
			<a class="nav-link dropdown-toggle" href="#" data-toggle="dropdown" role="button"
				aria-haspopup="true" aria-expanded="false">
				<span class="rayher-lang-label">${frappe.utils.escape_html(current_label)}</span>
			</a>
			<ul class="dropdown-menu dropdown-menu-right">${items}</ul>
		</li>
	`);

	$li.on('click', '[data-lang]', function (e) {
		e.preventDefault();
		rayher.i18n.set_language($(this).attr('data-lang'));
	});

	$navbar.prepend($li);
	return true;
};

$(document).on('startup', () => rayher.i18n.render_switcher());
$(document).ready(() => {
	// Navbar may render after this script; retry briefly until it is present.
	let tries = 0;
	const timer = setInterval(() => {
		if (rayher.i18n.render_switcher() || ++tries > 20) {
			clearInterval(timer);
		}
	}, 500);
});
