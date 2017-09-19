import logging
import gi
from gi.repository import GLib
from eduvpn.util import error_helper, thread_helper
from eduvpn.remote import create_keypair, get_profile_config
from eduvpn.manager import store_provider
from eduvpn.notify import notify
from eduvpn.steps.provider import update_providers

logger = logging.getLogger(__name__)


def finalizing_step(builder, oauth, meta):
    """finalise the add profile flow, add a configuration"""
    logger.info("finalizing step")
    dialog = builder.get_object('fetch-dialog')
    dialog.show_all()
    thread_helper(lambda: _background(meta=meta, oauth=oauth, dialog=dialog, builder=builder))


def _background(meta, oauth, dialog, builder):
    try:
        cert, key = create_keypair(oauth, meta.api_base_uri)
        meta.cert = cert
        meta.key = key
        meta.config = get_profile_config(oauth, meta.api_base_uri, meta.profile_id)
    except Exception as e:
        GLib.idle_add(lambda: error_helper(dialog, "can't finalize configuration", "{}: {}".format(type(e).__name__,
                                                                                            str(e))))
        GLib.idle_add(lambda: dialog.hide())
        raise
    else:
        try:
            store_provider(meta)
            GLib.idle_add(notify, "eduVPN provider added", "added provider '{}'".format(meta.display_name))
        except Exception as e:
            GLib.idle_add(lambda: error_helper(dialog, "can't store configuration", "{} {}".format(type(e).__name__,
                                                                                            str(e))))
            GLib.idle_add(lambda: dialog.hide())
            raise
        else:
            GLib.idle_add(lambda: dialog.hide())
            GLib.idle_add(lambda: update_providers(builder))