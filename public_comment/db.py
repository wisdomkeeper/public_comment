import click
from flask import current_app, Flask, g
from flask.cli import with_appcontext
import sqlite3

from public_comment.const import *
from public_comment.models import *

class Row(sqlite3.Row):
    def __init__(self, cursor, values):
        self.cursor = cursor
        self.values = values
        self.columns = [col[0] for col in cursor.description]
        # self.val = " ".join([self._coerce_type(val, none='') for col, val in zip(self.columns, self.values) if 'val' in col]) # combines values with 'val in column name.

        for col, val in zip(self.columns, self.values):
            setattr(self, col, val)

    def get(self, attr:str):
        """
        Returns the value of `attr` if present
            else, returns None.
        """

        attribute = None
        try:
            attribute = getattr(self, attr)
        except AttributeError: pass

        return attribute

    def items(self):
        return zip(self.columns, self.values)

    def to_dict(self):
        return {col: val for col, val in zip(self.columns, self.values)}

    @staticmethod
    def _coerce_type(val, separator=",", none=None):
        """
        Coerces `val` as a float or int if applicable,
        if `val` is None, returns the value of `none`
        else returns original value.

        :param val: Value to coerce.
        """

        if val is None:
            val = none
        elif isinstance(val, str):
            if len(coll := val.split(separator)) > 1:
                val = [Model._coerce_type(elem.strip()) for elem in coll]

            try:
                if "." in str(val):
                    val = float(val)
                else:
                    val = int(val)
            except TypeError: pass
            except ValueError: pass

        return val

    def __getitem__(self, key:str):
        try:
            return getattr(self, key)
        except AttributeError:
            raise ValueError

    # def __repr__(self): return f"{self.val}"


class DataManager:
    @staticmethod
    def get_db() -> sqlite3.Connection:
        if 'db' not in g:
            g.db = sqlite3.connect(
                current_app.config['DATABASE'],
                detect_types=sqlite3.PARSE_DECLTYPES
            )
            g.db.row_factory = Row
        
        return g.db

    @staticmethod
    def coerce_type(val, separator=",", none=None):
        """
        Coerces `val` as a float or int if applicable,
        if `val` is None, returns the value of `none`
        else returns original value.

        :param val: Value to coerce.
        """

        if val is None:
            val = none
        elif isinstance(val, str):
            if len(coll := val.split(separator)) > 1:
                val = [Model._coerce_type(elem.strip()) for elem in coll]

            try:
                if "." in str(val):
                    val = float(val)
                else:
                    val = int(val)
            except (TypeError, ValueError):
                val = f"'{val}'"

        return val

    #TODO: somehow connect joining on the same table multiples times to the select columns
    @staticmethod
    def _join(from_table:str, join:dict) -> str:
        """
        Creates a left join clause for each table-column pair in `join`.
        """

        JOIN = ""
        if join:
            joins = []
            if isinstance(join, dict):
                for idx, (table, on) in enumerate(join.items()):
                    joins.append(f"LEFT JOIN {table} AS {table}{idx} ON {table}{idx}.{on} = {from_table}.{on}")
            elif self.is_iter(join):
                for idx, table in enumerate(join):
                    joins.append(f"LEFT JOIN {table} AS {table}{idx} ON {table}{idx}.{table}_id = {from_table}.{table}_id")
                raise NotImplementedError("Table names are plural; default id columns are singular.")
            
            JOIN = "\t\n".join(joins)

        return JOIN

    def get_columns(self, table:str) -> list:
        """
        Retrieves a list of `table` columns.

        :param table: Name of database table.
        :return: List of columns.
        """

        cursor = self.get_db().execute(f"SELECT * FROM {table} LIMIT 0")
        columns = [col[0] for col in cursor.description]

        return columns

    @staticmethod
    def _columns(columns) -> str:
        """
        If `columns` is a 
            str: returns unaltered.
            dict: joins table-column pairs as '`table`.column'.
            iterable: joins columns.
        """
        
        COLUMNS = ""
        if isinstance(columns, str):
            COLUMNS += columns
        elif isinstance(columns, dict):
            COLUMNS += ", ".join(f"`{table}`.{column}" for table, column in columns.items())
        elif hasattr(columns, "__iter__"):
            COLUMNS += ", ".join(columns)

        return COLUMNS

    @staticmethod
    def _where(conditions, pk='id', val='val') -> str:
        """
        """

        WHERE = ""
        try:
            WHERE += f"{pk} = {int(conditions)}"
        except ValueError:
            if isinstance(conditions, str):
                WHERE += f"{val} = '{conditions}'"
        except TypeError:
            if isinstance(conditions, dict):
                WHERE += " AND ".join([f"{col} = {DataManager.coerce_type(val)}" for col, val in conditions.items()])

        return WHERE

    def select(self, table:str, columns='*', join=None, where=None, datatype=None) -> list:
        """
        SELECT `columns` FROM `table`
        """

        SELECT = "SELECT {COLUMNS} FROM {TABLE} {JOIN} {WHERE}" \
            .format(
                COLUMNS=self._columns(columns),
                TABLE=table,
                JOIN=self._join(table, join),
                WHERE=f"WHERE {self._where(where)}" if where else ""
            )

        # results = self.get_db().execute(" ".join([SELECT, FROM, JOIN, WHERE])).fetchall()
        results = self.get_db().execute(SELECT).fetchall()
        if datatype:
            results = [datatype.from_row(result) for result in results]

        return results

    #TODO: columns parameter 
    #? and maybe intersection of table columns and values
    def insert(self, table:str, values:dict, datatype=None) -> None:
        """
        INSERT INTO `table` VALUES (`values`)
        """
        
        if datatype:
            new_obj = datatype.from_dict(values)
            values = new_obj.to_dict()

        cols = self.get_columns(table)[1:]
        INSERT = "INSERT INTO `{TABLE}` ({COLUMNS}) VALUES ({VALUES})".format(
            TABLE=table,
            COLUMNS=", ".join(cols),
            VALUES=", ".join("?" * len(cols))
        )

        db = self.get_db()
        db.execute(
            INSERT,
            [f"{values.get(key)}" for key in cols]
        )
        db.commit()

    def get_neighborhoods(self): return self.select(NEIGHBORHOODS, join={'npus': 'npu_id', 'zones': 'zone_id'}, datatype=Neighborhood)
    def get_zones(self): return self.select(ZONES, join={NEIGHBORHOODS: ZONE_ID}, datatype=Zone)
    def get_npus(self): return self.select(NPUs, join={NEIGHBORHOODS: NPU_ID}, datatype=NPU)
    def get_districts(self): return self.select(DISTRICTS, datatype=District)

    @staticmethod
    def is_iter(obj) -> bool:
        return hasattr(obj, '__iter__') and not isinstance(obj, str)

    @staticmethod
    def init_db():
        db = DataManager.get_db()

        with current_app.open_resource('schema.sql') as f:
            db.executescript(f.read().decode('utf8'))

    @staticmethod
    def init_app(app:Flask):
        app.teardown_appcontext(DataManager.close_db)
        app.cli.add_command(DataManager.init_db_command)
        
    @staticmethod
    def close_db(e=None):
        db = g.pop('db', None)

        if db is not None:
            db.close()

    @staticmethod
    @click.command('init-db')
    @with_appcontext
    def init_db_command():
        """ Clear the existing data and create new tables."""

        DataManager().init_db()
        click.echo(f"Initialized the database.")
