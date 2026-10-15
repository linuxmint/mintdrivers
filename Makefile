all: buildmo

buildmo:
	@echo "Building the mo files"
	for file in po/mainuan-gestao-drivers-*.po; do \
		lang=$${file#po/mainuan-gestao-drivers-}; lang=$${lang%.po}; \
		install -d usr/share/locale/$$lang/LC_MESSAGES/; \
		msgfmt -o usr/share/locale/$$lang/LC_MESSAGES/mainuan-gestao-drivers.mo $$file; \
	done

clean:
	rm -rf usr/share/locale
