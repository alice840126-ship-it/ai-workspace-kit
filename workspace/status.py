"""Local publication receipt; never presents a past sync as a live remote check."""


def publication_snapshot(ledger):
    configured = (ledger.state / 'github-repository.json').is_file()
    commit = ledger.get('remote_verified')
    stamped = ledger.get('synced_at')
    published = ledger.get('published_event_count')
    current = ledger.db.execute('select count(*) from events').fetchone()[0]
    warm_table = ledger.db.execute("select 1 from sqlite_master where type='table' and name='external_checkpoints'").fetchone()
    local_checkpoints = (ledger.db.execute('select count(*) from external_checkpoints where promoted_event is null').fetchone()[0]
                         if warm_table else 0)
    if not configured:
        state = 'not_configured'
    elif not commit or not stamped:
        state = 'never_verified'
    elif published is None:
        state = 'prior_receipt_without_event_baseline'
    elif current != int(published):
        state = 'local_refined_updates_after_sync'
    else:
        state = 'last_sync_verified'
    return {'state': state, 'last_verified_commit': commit[:12] if commit else None,
            'last_verified_at': stamped, 'refined_events': current,
            'local_checkpoints_not_promoted': local_checkpoints,
            'verification_scope': 'last_successful_sync_only'}
