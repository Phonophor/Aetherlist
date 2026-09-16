"""Run after installing requirements: python -m unittest test_catalog.py."""
import sqlite3
import unittest
import build_catalog as builder


class CatalogTest(unittest.TestCase):
    def test_faces_and_text_postings_match_stored_card(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        builder.schema(db)
        builder.user_schema(db)
        card = {'id': 'a', 'name': 'Front // Back', 'card_faces': [
            {'name': 'Front', 'oracle_text': 'Pay 7 life.', 'image_uris': {'normal': 'front'}, 'mana_cost': '{1}{W}', 'type_line': 'Creature — Test', 'power': '2', 'toughness': '3'},
            {'name': 'Back', 'oracle_text': 'Draw a card.', 'image_uris': {'normal': 'back'}, 'mana_cost': '{2}{U}', 'type_line': 'Creature — Test', 'power': '4', 'toughness': '5'}]}
        row = builder.card_row(card, 1)
        self.assertEqual(len(row), len(builder.CARD_COLUMNS))
        db.execute('INSERT INTO cards(' + ','.join(builder.CARD_COLUMNS) + ') VALUES(' + ','.join('?' for _ in row) + ')', row)
        builder.build_text_index(db)
        db.execute("INSERT INTO oracle_tags VALUES('draw','draw')")
        db.execute("INSERT INTO card_oracle_tags VALUES('a','draw',1.0)")
        db.execute("INSERT INTO art_tags VALUES('dragon','dragon')")
        db.execute("INSERT INTO illustration_art_tags VALUES('front','dragon',1.0)")
        builder.build_tag_row_indexes(db)
        self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 13)
        faces = db.execute('SELECT facesJson FROM cards').fetchone()[0]
        self.assertIn('back', faces)
        self.assertIn('\"mana_cost\":\"{2}{U}\"', faces)
        self.assertIn('\"power\":\"4\"', faces)
        self.assertIn('\"toughness\":\"5\"', faces)
        self.assertEqual(db.execute('SELECT rowIds FROM search_text_index WHERE field=?', ('oracleText',)).fetchone()[0], '1')
        self.assertEqual(db.execute("SELECT rowIds FROM search_oracle_tag_rows WHERE tagSlug='draw'").fetchone()[0], '1')
        self.assertEqual(db.execute("SELECT rowIds FROM search_art_tag_rows WHERE tagSlug='dragon'").fetchone()[0], '1')


if __name__ == '__main__':
    unittest.main()
