from unittest import TestCase

from kote.addressbook import Addressbook

vasya_dest = "3cmcwwwvitnh5y7nhmpsdiwadukzandg3bkzcvqvml5h4jmwtejq"
petya_dest = "5h4j3cmcwwwvitnh5y7nmwtejqhmpsdiwadukzandg3bkzcvqvml"
masha_dest = "tnh5y7nmwtejqhmps5h4j3cmcwwwvidivqvmlwadukzandg3bkzc"

class TestAddressbook(TestCase):

    def test_valid(self):
        ab = Addressbook()
        ab["vasya"] = vasya_dest
        ab["petya"] = petya_dest

        self.assertEqual(ab["vasya"], vasya_dest)
        self.assertEqual(ab.get_name(petya_dest), "petya")

        self.assertEqual(ab.get_name(masha_dest), None)

        ab.update({"masha": masha_dest})
        self.assertEqual(ab.get_name(masha_dest), "masha")

        self.assertTrue("petya" in ab.keys())
        self.assertTrue(petya_dest in ab.values())
        del ab["petya"]
        self.assertFalse("petya" in ab.keys())
        self.assertFalse(petya_dest in ab.values())

    def test_adding_error(self):
        ab = Addressbook()
        ab["vasya"] = vasya_dest
        ab["petya"] = petya_dest

        with self.assertRaises(ValueError):
            ab["vasya"] = masha_dest

        with self.assertRaises(ValueError):
            ab["masha"] = vasya_dest

        with self.assertRaises(ValueError):
            ab["masha"] = "illegal"

    def test_online(self):
        ab = Addressbook()
        ab["vasya"] = vasya_dest
        ab["petya"] = petya_dest

        ab.set_online(vasya_dest)
        self.assertTrue(ab.is_online(vasya_dest))
        self.assertFalse(ab.is_online(petya_dest))
        self.assertFalse(ab.is_online(masha_dest))
        self.assertEqual(len(ab.online_peers()), 1)

        ab["masha"] = masha_dest
        ab.set_online(masha_dest)
        self.assertEqual(len(ab.online_peers()), 2)

    def test_last_seen(self):
        ab = Addressbook()
        ab["vasya"] = vasya_dest
        ab["petya"] = petya_dest

        ab.set_online(vasya_dest)
        self.assertTrue(ab.last_seen(vasya_dest).startswith("0:00:0"))
        self.assertEqual(ab.last_seen(petya_dest), "never")

    def test_humans(self):
        ab = Addressbook()
        ab["vasya"] = vasya_dest
        ab["petya"] = petya_dest
        ab["TestBot"] = masha_dest

        self.assertEqual(len(ab.humans()), 2)
        del ab["vasya"]
        self.assertEqual(len(ab.humans()), 1)


class TestValidData(TestCase):

    def test_valid_address(self):
        res = Addressbook.is_valid_address(vasya_dest)
        self.assertTrue(bool(res))
        res = Addressbook.is_valid_address(petya_dest)
        self.assertTrue(bool(res))

    def test_invalid_address(self):
        res = Addressbook.is_valid_address("")
        self.assertFalse(res)
        res = Addressbook.is_valid_address("asd")
        self.assertFalse(res)
        res = Addressbook.is_valid_address(vasya_dest + "a")
        self.assertFalse(res)
        res = Addressbook.is_valid_address("щ"*52)
        self.assertFalse(res)

