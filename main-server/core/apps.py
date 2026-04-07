from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    # Django hook that gets called automatically once the app is loaded and ready to handle requests.
    def ready(self):
        import os
        import sys
        # runserver spawns a file-watcher parent and a worker child.
        # RUN_MAIN='true' is only set in the worker, so we skip the parent.
        # gunicorn never sets RUN_MAIN, so we always start there.
        if 'runserver' in sys.argv and os.environ.get('RUN_MAIN') != 'true':
            return
        from .election import election_manager
        election_manager.start_monitor()    # start the monitor which will run the leader election algorithm in the background.

        # Seed the SC token into server 1 on startup so the token ring is
        # immediately operational without manual intervention after restarts.
        if int(os.environ.get('SERVER_ID', 0)) == 1:
            from .consistency import token_ring_manager
            token_ring_manager.receive_token()
