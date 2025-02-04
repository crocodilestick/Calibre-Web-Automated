from datetime import datetime
from flask import (
    Blueprint,
    request,
    make_response,
    jsonify,
    abort
)
from .cw_login import current_user
from sqlalchemy.sql.expression import and_
from . import config, logger, db, calibre_db, ub, csrf
from .services import hardcover
from hashlib import md5
import time
#TODO handle auth better
from functools import wraps
from .cw_login import login_user, current_user
from . import limiter
from flask_limiter import RateLimitExceeded

kosync = Blueprint("kosync", __name__, url_prefix="/kosync")
# kobo_auth.disable_failed_auth_redirect_for_blueprint(kobo)
# kobo_auth.register_url_value_preprocessor(kobo)

log = logger.create()

def populate_document_hashes():
    start = time.time()
    books_missing_hash = calibre_db.session.query(db.Data).outerjoin(ub.KosyncBooks,db.Data.id == ub.KosyncBooks.data_id).where(ub.KosyncBooks.data_id == None).all()
    log.debug(len(books_missing_hash))
    for missing_hash in books_missing_hash:
        filename = f'{missing_hash.name}.{missing_hash.format.lower()}'
        hash = md5(filename.encode()).hexdigest()
        kosync_book = ub.KosyncBooks(data_id=missing_hash.id, book=missing_hash.book, document_hash=hash)
        ub.session.add(kosync_book)
    ub.session_commit()
    end = time.time()
    log.debug(f'Migrated {len(books_missing_hash)} records in {(end-start) * 10**3}ms')

def requires_kosync_auth(f):
    @wraps(f)
    def inner(*args, **kwargs):
        username = request.headers.get("X-Auth-User")
        key = request.headers.get("X-Auth-Key")
        if username is not None and key is not None:
            try:
                limiter.check()
            except RateLimitExceeded:
                return abort(429)
            except (ConnectionError, Exception) as e:
                log.error("Connection error to limiter backend: %s", e)
                return abort(429)
            user = (
                ub.session.query(ub.User)
                .filter(ub.User.name == username).filter(ub.User.kosync_password == key)
                .first()
            )
            if user is not None:
                login_user(user)
                [limiter.limiter.storage.clear(k.key) for k in limiter.current_limits]
                return f(*args, **kwargs)
        log.debug("Received Kosync request without a recognizable auth headers.")
        return abort(make_response(jsonify({"message":"Unauthorized"}),401))
    return inner

# At this time no reason to create users from endpoint.
# @csrf.exempt
# @kosync.route("/users/create", methods=['GET','POST'])
# @requires_kosync_auth
# def HandleUserCreate():

@kosync.route("/users/auth")
@requires_kosync_auth
def HandleUserAuth():
    log.debug(request)
    return make_response(jsonify({"authorized":"OK"}),200)

@csrf.exempt
@kosync.route("/syncs/progress", methods=['PUT'])
@requires_kosync_auth
def HandleUpdateProgress():
    sync_data = request.json    
    sync = ub.session.query(ub.Kosync).where(and_(ub.Kosync.user_id == current_user.id, ub.Kosync.document_hash == sync_data["document"])).scalar()
    if not sync:
        sync = ub.Kosync(document_hash = sync_data["document"], user_id = current_user.id)
        ub.session.add(sync)
    sync.progress = sync_data["progress"]
    sync.percentage = sync_data["percentage"]
    sync.device = sync_data["device"]
    sync.device_id = sync_data["device_id"]
    sync.timestamp = datetime.now()
    ub.session_commit()
    if config.config_hardcover_sync and bool(hardcover):
        book = calibre_db.session.query(db.Books).join(ub.KosyncBooks, ub.KosyncBooks.book == db.Books).where(ub.KosyncBooks.document_hash == sync_data["document"]).scalar()
        hardcoverClient = hardcover.HardcoverClient(current_user.hardcover_token)
        hardcoverClient.update_reading_progress(book.identifiers, sync.percentage)
    return make_response(jsonify({"document":sync.document_hash,"timestamp":sync.timestamp}),200)

@kosync.route("/syncs/progress/<document_hash>")
@requires_kosync_auth
def HandleGetProgress(document_hash):
    sync = ub.session.query(ub.Kosync).where(and_(ub.Kosync.user_id == current_user.id, ub.Kosync.document_hash == document_hash)).scalar()
    if not sync:
        return make_response(jsonify({"message":"Document not found"}),502)
    return make_response(jsonify({
        "device":sync.device,
        "device_id":sync.device_id,
        "document":sync.document_hash,
        "percentage":sync.percentage,
        "progress":sync.progress
    }),200)